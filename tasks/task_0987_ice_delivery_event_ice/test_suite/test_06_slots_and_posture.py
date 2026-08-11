"""Delivery-slot reservation gauntlet and depot posture gating (PRD §2.9, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    agent,
    confirmed_order,
    get_depot,
    get_success_data,
    make_active_book,
    make_customer,
    make_depot,
    make_slot,
    mini_book_payload,
    order_line,
    quote,
    quoted_order,
    reserve,
    run_ops,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _setup(customer_name, depot_name, capacity=10, limit=500000):
    depot = make_depot(capacity, depot_name)
    set_logical_clock()
    make_active_book(mini_book_payload())
    cust = make_customer(
        account_name=customer_name, kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=limit,
    )
    return depot, cust


def test_window_outside_slot_rejected(api):
    """PRD §3.5: "first containment — the slot's window must cover the order's
    window, slot start no later than order start and order end no later than
    slot end, else `ERR_WINDOW_OUTSIDE_SLOT`".

    Design: Corner/validations/window_outside_slot_rejected
    """
    depot, cust = _setup("V33", "Depot V33", limit=200000)
    slot = make_slot(depot["id"], date="2026-05-12", window_start="08:00",
                     window_end="18:00", capacity_pallets=5)
    order = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="DELIVERY", event_date="2026-05-12",
        window_start="17:00", window_end="19:00",
    )
    resp = api.reserve_slot(
        order["id"], {"delivery_slot_id": slot["id"]}, agent(cust["id"])
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_SLOT)


def test_posture_frozen_blocks_reserve(api):
    """PRD §2.9: "a `FROZEN` depot accepts no new slot reservations
    (`ERR_POSTURE_FROZEN`) and blocks waitlist promotion until a release eases
    it."
    PRD §2.9: "`FROZEN` when no pallet space remains — the free count at or
    below zero".

    Design: Corner/errors/posture_frozen_blocks_reserve
    """
    depot, cust = _setup("E47", "Depot E47", capacity=1)
    order_a = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    confirm_a = validate_success(api.confirm_order(order_a["id"], agent(cust["id"])))
    assert confirm_a["fulfillment_status"] == "CONFIRMED"
    assert get_depot(depot["id"])["posture"] == "FROZEN", (
        "cap 1 fully reserved: free count 0"
    )

    slot = make_slot(depot["id"], date="2026-05-12", capacity_pallets=5)
    order_b = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="DELIVERY", event_date="2026-05-12",
        window_start="09:00", window_end="11:00",
    )
    resp = api.reserve_slot(
        order_b["id"], {"delivery_slot_id": slot["id"]}, agent(cust["id"])
    )
    validate_error(resp, ApiErrorId.ERR_POSTURE_FROZEN)


def test_clock_default_and_past_slot_rejected(api):
    """PRD §2.4: "At startup the clock reads exactly 2026-05-01T00:00:00Z;
    before any administrative intervention it continues to read that default,
    and it never falls back to wall-clock time."
    PRD §3.5: "A `Dispatcher` opens a slot for a depot with a `date` no earlier
    than the current logical date (`ERR_DELIVERY_WINDOW_PAST`)".

    Design: Corner/errors/clock_default_and_past_slot_rejected
    """
    depot = make_depot(10, "Depot E48")
    # No set_clock call: the startup default 2026-05-01 applies.
    ok = validate_success(
        api.create_delivery_slot(
            {
                "depot_id": depot["id"],
                "date": "2026-05-01",
                "window_start": "08:00",
                "window_end": "18:00",
                "capacity_pallets": 5,
            },
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert ok["id"], "a slot dated with the default logical today is admitted"

    resp = api.create_delivery_slot(
        {
            "depot_id": depot["id"],
            "date": "2026-04-30",
            "window_start": "08:00",
            "window_end": "18:00",
            "capacity_pallets": 5,
        },
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_PAST)


def test_slot_closure_sweep(api):
    """PRD §3.5: "Once the slot's date falls behind the current logical date,
    the ops-run closure sweep moves it to `CLOSED`; historical reservations are
    unaffected, but no new reservation is accepted."

    Design: Corner/state_machines/slot_closure_sweep
    """
    depot = make_depot(10, "Depot S14")
    set_logical_clock()
    slot = make_slot(depot["id"], date="2026-05-02", capacity_pallets=5)
    set_logical_clock("2026-05-03T09:00:00Z")
    ops = run_ops(depot["id"])
    assert slot["id"] in ops["closed_slot_ids"]

    slots, _meta = validate_paginated(
        api.list_delivery_slots(depot["id"], DISPATCHER)
    )
    assert slots[0]["status"] == "CLOSED"


# ----------------- difficulty: slot capacity boundary --------------------------

def _quoted_delivery(cust, depot, event_window):
    return quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", event_window[2])],
        channel="DELIVERY", event_date="2026-05-12",
        window_start=event_window[0], window_end=event_window[1],
    )


def test_slot_capacity_exact_fill_flips_full(api):
    """PRD §3.5: "then capacity — the slot's reserved pallets plus the order's
    `pallets_required` must not exceed `capacity_pallets`, with equality
    admitted, else `ERR_SLOT_CAPACITY_EXCEEDED`."
    PRD §3.5: "the slot turns `FULL` the moment the reserved total reaches
    capacity, and releases can return it to `OPEN`".

    Design: Difficulty/boundary_precision_check/slot_capacity_exact_fill_flips_full
    """
    depot, cust = _setup("BP2", "Depot BP2")
    slot = make_slot(depot["id"], date="2026-05-12", capacity_pallets=3)
    d1 = _quoted_delivery(cust, depot, ("09:00", "11:00", 2))
    d2 = _quoted_delivery(cust, depot, ("12:00", "13:00", 1))
    d3 = _quoted_delivery(cust, depot, ("14:00", "15:00", 1))

    r1 = reserve(d1["id"], cust["id"], slot["id"])
    assert r1["delivery_slot_id"] == slot["id"], "2 of 3 reserved, still OPEN"
    reserve(d2["id"], cust["id"], slot["id"])

    slots, _meta = validate_paginated(
        api.list_delivery_slots(depot["id"], DISPATCHER, params={"date": "2026-05-12"})
    )
    assert slots[0]["reserved_pallets"] == 3
    assert slots[0]["status"] == "FULL", "exact equality 3 == 3 flips OPEN -> FULL"

    resp = api.reserve_slot(d3["id"], {"delivery_slot_id": slot["id"]}, agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)
    # 3 + 1 > 3


def test_slot_full_reopens_after_quoted_cancel(api):
    """PRD §3.5: "the slot turns `FULL` the moment the reserved total reaches
    capacity, and releases can return it to `OPEN`".
    PRD §3.6: "From `QUOTED`, a held slot reservation is released:
    `delivery_slot_id` clears, the slot's reserved total drops by the order's
    pallets, and a `FULL` slot can reopen to `OPEN`."

    Design: Difficulty/boundary_precision_check/slot_capacity_exact_fill_flips_full
    """
    depot, cust = _setup("BP2b", "Depot BP2b")
    slot = make_slot(depot["id"], date="2026-05-12", capacity_pallets=3)
    d1 = _quoted_delivery(cust, depot, ("09:00", "11:00", 2))
    d2 = _quoted_delivery(cust, depot, ("12:00", "13:00", 1))
    d3 = _quoted_delivery(cust, depot, ("14:00", "15:00", 1))
    reserve(d1["id"], cust["id"], slot["id"])
    reserve(d2["id"], cust["id"], slot["id"])

    slots, _meta = validate_paginated(
        api.list_delivery_slots(depot["id"], DISPATCHER, params={"date": "2026-05-12"})
    )
    assert slots[0]["status"] == "FULL"

    validate_success(api.cancel_order(d2["id"], agent(cust["id"])))
    slots, _meta = validate_paginated(
        api.list_delivery_slots(depot["id"], DISPATCHER, params={"date": "2026-05-12"})
    )
    assert slots[0]["reserved_pallets"] == 2
    assert slots[0]["status"] == "OPEN", "release below capacity reopens"

    r3 = reserve(d3["id"], cust["id"], slot["id"])
    assert r3["delivery_slot_id"] == slot["id"], "reservation admitted after reopen"
    slots, _meta = validate_paginated(
        api.list_delivery_slots(depot["id"], DISPATCHER, params={"date": "2026-05-12"})
    )
    assert slots[0]["reserved_pallets"] == 3
    assert slots[0]["status"] == "FULL"
