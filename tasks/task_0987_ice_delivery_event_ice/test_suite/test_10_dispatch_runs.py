"""Dispatch-run assignment, capacity checks, and run lifecycle (PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    confirmed_delivery_order,
    first_hold_id,
    get_depot,
    get_order,
    get_success_data,
    make_active_book,
    make_certification,
    make_customer,
    make_depot,
    make_run,
    make_slot,
    mini_book_payload,
    mini_dry_book_payload,
    order_line,
    quoted_order,
    reserve,
    confirm,
    stage,
    staged_delivery_order,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DEPOT_MGR = TEST_USERS["depot_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _setup(customer_name, depot_name, book=None, limit=200000):
    depot = make_depot(10, depot_name)
    set_logical_clock()
    make_active_book(book or mini_book_payload())
    cust = make_customer(
        account_name=customer_name, kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=limit,
    )
    return depot, cust


def test_dispatch_happy_path_delivers_order(api):
    """PRD §3.7: "Starting requires at least one assigned order
    (`ERR_INVALID_STATE`) and moves `LOCKED` to `IN_PROGRESS` with a three-hop
    cascade: each assigned order goes from `STAGED` to `IN_TRANSIT`; each such
    order's `OCCUPIED` hold is `RELEASED` — the product has left the freezer —
    returning its pallets to the depot".
    PRD §3.7: "Completion moves `IN_PROGRESS` to `COMPLETED`: every assigned
    order goes from `IN_TRANSIT` to `DELIVERED` with `fulfilled_at` stamped
    from the logical clock, becoming invoice-eligible while its
    `billing_status` stays `UNBILLED` (§3.8)."

    Design: Corner/state_machines/dispatch_happy_path_delivers_order
    """
    depot, cust = _setup("S19", "Depot S19")
    slot = make_slot(depot["id"], date="2026-05-12", capacity_pallets=5)
    order = staged_delivery_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)], slot["id"],
        event_date="2026-05-12", window_start="09:00", window_end="11:00",
    )
    assert order["total_cents"] == 22500, (
        "21000 + 1500 deposit; post-discount 21000 >= 20000 waives the fee"
    )

    run = make_run(depot["id"], run_date="2026-05-12", vehicle_label="TRUCK-1",
                   max_pallets=5, ventilated_dry_ice_cap_lbs=0)
    validate_success(api.assign_run(run["id"], {"order_ids": [order["id"]]}, DISPATCHER))
    validate_success(api.lock_run(run["id"], DISPATCHER))

    started = validate_success(api.start_run(run["id"], DISPATCHER))
    assert started["status"] == "IN_PROGRESS"
    assert started["assigned_pallets"] == 1
    order_mid = get_order(order["id"], DISPATCHER)
    assert order_mid["fulfillment_status"] == "IN_TRANSIT"
    holds_mid, _meta = validate_paginated(api.list_order_holds(order["id"], DISPATCHER))
    assert holds_mid[0]["status"] == "RELEASED", "product left the freezer"

    completed = validate_success(api.complete_run(run["id"], DISPATCHER))
    assert completed["status"] == "COMPLETED"
    order_end = get_order(order["id"], DISPATCHER)
    assert order_end["fulfillment_status"] == "DELIVERED"
    assert order_end["fulfilled_at"] is not None
    assert order_end["billing_status"] == "UNBILLED"


def test_assign_atomic_rejection_mixed_states(api):
    """PRD §3.7: "every listed order must be `STAGED`, channel `DELIVERY`,
    homed at the run's depot, dated to the run's `run_date`, and not already
    linked to a run (`ERR_INVALID_STATE`)."
    PRD §3.7: "Any violation rejects the entire assignment — no partial links".

    Design: Corner/state_machines/assign_atomic_rejection_mixed_states
    """
    depot, cust = _setup("S20", "Depot S20", limit=500000)
    slot = make_slot(depot["id"], date="2026-05-12", capacity_pallets=10)
    ord_s = staged_delivery_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)], slot["id"],
        event_date="2026-05-12", window_start="09:00", window_end="11:00",
    )
    ord_q = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="DELIVERY", event_date="2026-05-12",
        window_start="12:00", window_end="13:00",
    )
    run = make_run(depot["id"], run_date="2026-05-12", vehicle_label="TRUCK-2",
                   max_pallets=10, ventilated_dry_ice_cap_lbs=1000)

    resp = api.assign_run(
        run["id"], {"order_ids": [ord_s["id"], ord_q["id"]]}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    manifest, _meta = validate_paginated(api.list_run_orders(run["id"], DISPATCHER))
    assert manifest == [], "atomic: no partial links"
    s_after = get_order(ord_s["id"], DISPATCHER)
    assert s_after["dispatch_run_id"] is None
    assert s_after["fulfillment_status"] == "STAGED", "untouched by the rejection"


def test_ventilation_capacity_on_assign(api):
    """PRD §3.7: "Two aggregate checks then apply, ventilation before deck
    capacity: the run's committed dry-ice pounds plus the candidates'
    `dry_ice_lbs` must stay within `ventilated_dry_ice_cap_lbs`
    (`ERR_DRY_ICE_VENTILATION_EXCEEDED`)".

    Design: Corner/state_machines/ventilation_capacity_on_assign
    """
    depot, cust = _setup("S21", "Depot S21", book=mini_dry_book_payload(), limit=500000)
    make_certification(
        cust["id"], handler_name="Hank Handler", certificate_number="CERT-21",
        max_dry_ice_lbs=1000, expires_at="2027-01-01T00:00:00Z",
    )
    slot = make_slot(depot["id"], date="2026-05-12", capacity_pallets=10)
    order = staged_delivery_order(
        cust["id"], depot["id"], [order_line("DRY_ICE", "BAG", 13)], slot["id"],
        event_date="2026-05-12", window_start="09:00", window_end="11:00",
    )
    assert order["dry_ice_lbs"] == 130
    run = make_run(depot["id"], run_date="2026-05-12", vehicle_label="TRUCK-3",
                   max_pallets=10, ventilated_dry_ice_cap_lbs=100)

    resp = api.assign_run(run["id"], {"order_ids": [order["id"]]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DRY_ICE_VENTILATION_EXCEEDED)
    # 130 lbs > 100 lbs cap (pallet capacity was ample)


def test_run_pallet_capacity_exceeded(api):
    """PRD §3.7: "the committed pallets plus the candidates'
    `pallets_required` must stay within `max_pallets`
    (`ERR_RUN_CAPACITY_EXCEEDED`)".

    Design: Corner/state_machines/run_pallet_capacity_exceeded
    """
    depot, cust = _setup("S22", "Depot S22", limit=500000)
    slot = make_slot(depot["id"], date="2026-05-12", capacity_pallets=10)
    order = staged_delivery_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 2)], slot["id"],
        event_date="2026-05-12", window_start="09:00", window_end="11:00",
    )
    assert order["pallets_required"] == 2
    run = make_run(depot["id"], run_date="2026-05-12", vehicle_label="VAN-1",
                   max_pallets=1, ventilated_dry_ice_cap_lbs=1000)

    resp = api.assign_run(run["id"], {"order_ids": [order["id"]]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_RUN_CAPACITY_EXCEEDED)
    # 2 pallets > max 1


def test_hold_manual_release(api):
    """PRD §3.6: "A `DepotManager` may also release a `RESERVED` or `OCCUPIED`
    hold manually — a damaged-stock write-off, for instance — which frees the
    space while leaving the linked order's own state untouched."

    Design: Corner/state_machines/hold_manual_release
    """
    depot, cust = _setup("S23", "Depot S23")
    order = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    confirm(order["id"], cust["id"])
    hold_id = first_hold_id(order["id"])

    released = validate_success(api.release_hold(hold_id, DEPOT_MGR))
    assert released["status"] == "RELEASED"

    order_after = get_order(order["id"], DEPOT_MGR)
    assert order_after["fulfillment_status"] == "CONFIRMED", (
        "release does not cancel the order"
    )
    assert get_depot(depot["id"])["freezer_free_pallets"] == 10
