"""Cold-storage capacity rules: exclusive bunker intervals, freezer
peak-overlap, and pallet conservation (PRD §2.9, §3.5, §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    agent,
    confirm,
    confirmed_order,
    full_book_payload,
    get_depot,
    make_active_book,
    make_certification,
    make_customer,
    make_depot,
    make_order,
    mini_book_payload,
    order_line,
    pickup,
    quote,
    quoted_order,
    set_logical_clock,
    stage,
    mark_ready,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DEPOT_MGR = TEST_USERS["depot_manager_headers"]

DRY_LINE = [order_line("DRY_ICE", "BAG", 1)]


def _setup_dry(customer_name, depot_name, capacity=10):
    depot = make_depot(capacity, depot_name)
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name=customer_name, kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    make_certification(
        cust["id"], handler_name="Hank Handler", certificate_number="CERT-1",
        max_dry_ice_lbs=1000, expires_at="2027-01-01T00:00:00Z",
    )
    return depot, cust


def _dry_quoted(cust, depot, window_start, window_end):
    return quoted_order(
        cust["id"], depot["id"], DRY_LINE,
        channel="WILL_CALL", event_date="2026-05-10",
        window_start=window_start, window_end=window_end,
    )


# ----------------- difficulty: bunker exclusive buffer adjacency ----------------

def test_bunker_overlap_rejected_and_buffer_adjacency_admitted(api):
    """PRD §3.5: "If that interval intersects any other cold-storage hold of
    the same depot zoned `DRY_ICE_BUNKER` and currently `RESERVED` or
    `OCCUPIED`, confirmation is rejected with `ERR_HOLD_INTERVAL_CONFLICT`."
    PRD §3.5: "Intervals are half-open: a candidate whose window starts exactly
    when an existing buffered interval ends is admitted, so adjacency at the
    ventilation-buffer boundary is allowed."

    Design: Difficulty/resource_temporal_overlap/bunker_exclusive_buffer_adjacency
    """
    depot, cust = _setup_dry("TO1 Events", "Depot TO1")
    order_a = _dry_quoted(cust, depot, "10:00", "12:00")
    confirmed_a = confirm(order_a["id"], cust["id"])
    assert confirmed_a["fulfillment_status"] == "CONFIRMED", (
        "A occupies the buffered interval [10:00, 13:30)"
    )

    order_c = _dry_quoted(cust, depot, "13:15", "14:00")
    resp_c = api.confirm_order(order_c["id"], agent(cust["id"]))
    validate_error(resp_c, ApiErrorId.ERR_HOLD_INTERVAL_CONFLICT)
    # [13:15, 15:30) intersects [10:00, 13:30)

    order_b = _dry_quoted(cust, depot, "13:30", "15:00")
    confirmed_b = confirm(order_b["id"], cust["id"])
    assert confirmed_b["fulfillment_status"] == "CONFIRMED", (
        "half-open adjacency: 13:30 == A's buffered end is admitted"
    )


def test_bunker_left_adjacency_and_one_minute_overlap(api):
    """PRD §3.5: "Intervals are half-open: a candidate whose window starts
    exactly when an existing buffered interval ends is admitted, so adjacency
    at the ventilation-buffer boundary is allowed."
    PRD §3.5: "The candidate's buffered interval runs from the event window's
    start to ninety minutes past its end — a sixty-minute grace for pickup or
    dispatch plus a thirty-minute ventilation buffer, both pinned constants."

    Design: Difficulty/resource_temporal_overlap/bunker_exclusive_buffer_adjacency
    """
    depot, cust = _setup_dry("TO1b Events", "Depot TO1b")
    order_a = _dry_quoted(cust, depot, "10:00", "12:00")
    confirm(order_a["id"], cust["id"])

    # Buffered [07:00, 10:00): ends exactly when A's buffered interval starts.
    order_d = _dry_quoted(cust, depot, "07:00", "08:30")
    confirmed_d = confirm(order_d["id"], cust["id"])
    assert confirmed_d["fulfillment_status"] == "CONFIRMED", (
        "adjacency at the left buffer boundary is admitted"
    )

    # Buffered [07:00, 10:01): one minute into A's interval -> conflict.
    order_e = _dry_quoted(cust, depot, "07:00", "08:31")
    resp_e = api.confirm_order(order_e["id"], agent(cust["id"]))
    validate_error(resp_e, ApiErrorId.ERR_HOLD_INTERVAL_CONFLICT)


# ----------------- difficulty: freezer peak-overlap aggregate --------------------

def _block_quoted(cust, depot, window_start, window_end, capacity_date="2026-05-10"):
    return quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date=capacity_date,
        window_start=window_start, window_end=window_end,
    )


def test_freezer_peak_overlap_aggregate(api):
    """PRD §3.5: "At every instant within it, the pallets held by overlapping
    same-depot general-freezer holds in `RESERVED` or `OCCUPIED`, plus the
    candidate's own `pallets_required`, must stay within the depot's
    `freezer_capacity_pallets`; any instant that would overflow rejects the
    confirmation with `ERR_FREEZER_CAPACITY_EXCEEDED`."
    PRD §2.9: "a `FROZEN` depot accepts no new slot reservations
    (`ERR_POSTURE_FROZEN`) and blocks waitlist promotion until a release eases
    it."

    Design: Difficulty/resource_temporal_overlap/freezer_peak_overlap_aggregate
    """
    depot = make_depot(2, "Depot TO2")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="TO2 Events", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    # X [06:00,13:00) and Y [06:30,12:30): peak 2 <= cap 2.
    order_x = _block_quoted(cust, depot, "10:00", "12:00")
    assert confirm(order_x["id"], cust["id"])["fulfillment_status"] == "CONFIRMED"
    order_y = _block_quoted(cust, depot, "10:30", "11:30")
    assert confirm(order_y["id"], cust["id"])["fulfillment_status"] == "CONFIRMED"

    # Z [07:00,13:00) overlaps both: peak 3 > 2.
    order_z = _block_quoted(cust, depot, "11:00", "12:00")
    resp_z = api.confirm_order(order_z["id"], agent(cust["id"]))
    validate_error(resp_z, ApiErrorId.ERR_FREEZER_CAPACITY_EXCEEDED)

    # W [14:00,20:00) is disjoint from X and Y (half-open touch at 13:00);
    # posture FROZEN does not gate confirmation.
    order_w = _block_quoted(cust, depot, "18:00", "19:00")
    confirmed_w = confirm(order_w["id"], cust["id"])
    assert confirmed_w["fulfillment_status"] == "CONFIRMED"


def test_freezer_adjacent_windows_still_overlap_via_buffers(api):
    """PRD §3.5: "The candidate interval runs from four hours before the event
    window's start — the staging lead — to sixty minutes past its end."
    PRD §3.5: "At every instant within it, the pallets held by overlapping
    same-depot general-freezer holds in `RESERVED` or `OCCUPIED`, plus the
    candidate's own `pallets_required`, must stay within the depot's
    `freezer_capacity_pallets`".

    Design: Difficulty/resource_temporal_overlap/freezer_peak_overlap_aggregate
    """
    depot = make_depot(2, "Depot TO2b")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="TO2b Events", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    # Event windows touch at 12:00, but the buffered hold intervals
    # [06:00,13:00) and [08:00,15:00) overlap: peak 2 <= cap 2 admits both.
    order_p = _block_quoted(cust, depot, "10:00", "12:00")
    assert confirm(order_p["id"], cust["id"])["fulfillment_status"] == "CONFIRMED"
    order_q = _block_quoted(cust, depot, "12:00", "14:00")
    confirmed_q = confirm(order_q["id"], cust["id"])
    assert confirmed_q["fulfillment_status"] == "CONFIRMED", (
        "overlapping buffered intervals at exactly capacity are admitted"
    )
    depot_after = get_depot(depot["id"])
    assert depot_after["freezer_reserved_pallets"] == 2
    assert depot_after["posture"] == "FROZEN"


# ----------------- difficulty: pallet reserve/cancel conservation -----------------

def test_pallet_hold_reserve_cancel_conservation(api):
    """PRD §2.9: "`freezer_reserved_pallets` is the sum of `pallets_required`
    across the depot's holds currently in `RESERVED` or `OCCUPIED` status, and
    `freezer_free_pallets` is the `freezer_capacity_pallets` less that reserved
    total."
    PRD §3.6: "Hop one: the order's `RESERVED` hold moves to `RELEASED` and its
    pallets leave the depot's reserved total."

    Design: Difficulty/compensating_invariant/pallet_hold_reserve_cancel_conservation
    """
    depot = make_depot(10, "Depot CI1")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="CI1 Events", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    before = get_depot(depot["id"])
    assert before["freezer_reserved_pallets"] == 0
    assert before["freezer_free_pallets"] == 10

    order = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    confirm(order["id"], cust["id"])
    mid = get_depot(depot["id"])
    assert mid["freezer_reserved_pallets"] == 2
    assert mid["freezer_free_pallets"] == 8, "confirm reserved 2 pallet spaces"

    validate_success(api.cancel_order(order["id"], agent(cust["id"])))
    after = get_depot(depot["id"])
    assert after["freezer_reserved_pallets"] == before["freezer_reserved_pallets"]
    assert after["freezer_free_pallets"] == before["freezer_free_pallets"], (
        "reserve + cancel conserve pallet spaces"
    )

    holds, _meta = validate_paginated(api.list_order_holds(order["id"], ADMIN))
    assert holds[0]["status"] == "RELEASED", (
        "the formula input set {RESERVED, OCCUPIED} is empty again"
    )


def test_pallet_hold_conserved_through_stage_and_pickup(api):
    """PRD §3.6: "The hold flips from `RESERVED` to `OCCUPIED` — the depot's
    reserved total is unchanged, but the occupancy clock starts".
    PRD §2.9: "`freezer_reserved_pallets` is the sum of `pallets_required`
    across the depot's holds currently in `RESERVED` or `OCCUPIED` status".

    Design: Difficulty/compensating_invariant/pallet_hold_reserve_cancel_conservation
    """
    depot = make_depot(10, "Depot CI1b")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="CI1b Events", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=200000,
    )
    order = quoted_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    confirm(order["id"], cust["id"])
    assert get_depot(depot["id"])["freezer_reserved_pallets"] == 2

    stage(order["id"])
    staged_depot = get_depot(depot["id"])
    assert staged_depot["freezer_reserved_pallets"] == 2, (
        "OCCUPIED still counts: staging does not change the reserved total"
    )
    assert staged_depot["freezer_free_pallets"] == 8

    mark_ready(order["id"])
    pickup(order["id"], cust["id"])
    after = get_depot(depot["id"])
    assert after["freezer_reserved_pallets"] == 0
    assert after["freezer_free_pallets"] == 10, (
        "pickup released the hold and restored the free count"
    )
    holds, _meta = validate_paginated(api.list_order_holds(order["id"], ADMIN))
    assert holds[0]["status"] == "RELEASED"
