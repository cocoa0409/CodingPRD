"""Validation-priority conflict, boundary-precision, and resource-overlap depth
tests (PRD §3.4, §3.5, §3.8, §3.10, §3.12).

Queue A — difficulty rules priority_pair_validation_conflict,
boundary_precision_check, and resource_temporal_overlap.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_customer, create_sku, create_tier, create_ticket, create_bay,
    create_under_review_claim, get_sku, create_order, add_order_line,
    create_special_order,
    create_warranty_claim_payload, approve_warranty_payload, reserve_payload,
    create_bay_booking_payload, create_special_order_payload,
    TEST_USERS,
)

MGR = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
ADV = TEST_USERS["service_advisor_headers"]


# ════════════════════════════════════════════════════════════════════════════
# Rule 5 — priority_pair_validation_conflict / deliver_pending_unpaid_state_beats_fiscal
# ════════════════════════════════════════════════════════════════════════════
def test_deliver_pending_unpaid_returns_invalid_state_not_fiscal():
    """PRD §3.12: "Then state is checked: a transition not defined from the
    resource's current state yields `ERR_INVALID_STATE`."
    PRD §3.12: "The fiscal gates follow: delivering an unpaid order yields
    `ERR_NOT_FULLY_PAID`".

    A PENDING, UNPAID order violates both the state precondition (priority 5) and
    the fiscal one (priority 14); state precedes fiscal, so delivery returns
    ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/deliver_pending_unpaid_state_beats_fiscal
    """
    cust = create_customer()
    sku = create_sku(name="Pedal Set", category="PART", list_price_cents=5000, on_hand=5)
    order = create_order(cust["id"])
    add_order_line(order["id"], sku["id"], 1)
    res = api_client.deliver_sales_order(order["id"], SA)
    validate_error(res, "ERR_INVALID_STATE")


def test_deliver_pending_unpaid_status_409():
    """PRD §3.5: "Delivery is permitted only from `RESERVED`".
    PRD §3.12: "a transition not defined from the resource's current state yields
    `ERR_INVALID_STATE`."

    The same PENDING|UNPAID delivery attempt is rejected with HTTP 409.

    Design: Difficulty/priority_pair_validation_conflict/deliver_pending_unpaid_state_beats_fiscal
    """
    cust = create_customer()
    sku = create_sku(name="Pedal Set B", category="PART", list_price_cents=5000, on_hand=5)
    order = create_order(cust["id"])
    add_order_line(order["id"], sku["id"], 1)
    res = api_client.deliver_sales_order(order["id"], SA)
    assert res.status_code == 409
    validate_error(res, "ERR_INVALID_STATE")


# ════════════════════════════════════════════════════════════════════════════
# Rule 6 — boundary_precision_check / reserve_exact_available_succeeds_one_more_fails
# ════════════════════════════════════════════════════════════════════════════
def test_reserve_exactly_available_succeeds():
    """PRD §3.5: "requires that every line's `Sku` have enough availability;
    availability is evaluated over the summed quantity of all lines for the same
    `Sku` within the request".

    Reserving qty 3 against on_hand 3 (available 3) succeeds and leaves
    reserved=3 — the boundary is available >= qty.

    Design: Difficulty/boundary_precision_check/reserve_exact_available_succeeds_one_more_fails
    """
    cust = create_customer()
    sku = create_sku(name="Tire", category="PART", list_price_cents=4000, on_hand=3)
    order = create_order(cust["id"])
    add_order_line(order["id"], sku["id"], 3)
    fresh = get_sku(sku["id"])
    validate_success(api_client.reserve_sales_order(order["id"], reserve_payload(fresh["version"]), SA), 200)
    sku_after = validate_success(api_client.get_sku(sku["id"], MGR), 200)
    assert sku_after["reserved"] == 3


def test_reserve_one_more_than_available_fails():
    """PRD §3.5: "If availability is insufficient the reserve fails with
    `ERR_INSUFFICIENT_STOCK`."

    After reserving all 3 units (available now 0), a second order reserving 1
    more fails with ERR_INSUFFICIENT_STOCK — the X+1 side of the boundary.

    Design: Difficulty/boundary_precision_check/reserve_exact_available_succeeds_one_more_fails
    """
    cust = create_customer()
    sku = create_sku(name="Tire B", category="PART", list_price_cents=4000, on_hand=3)
    order1 = create_order(cust["id"])
    add_order_line(order1["id"], sku["id"], 3)
    v0 = get_sku(sku["id"])["version"]
    validate_success(api_client.reserve_sales_order(order1["id"], reserve_payload(v0), SA), 200)
    order2 = create_order(cust["id"])
    add_order_line(order2["id"], sku["id"], 1)
    v2 = get_sku(sku["id"])["version"]
    res = api_client.reserve_sales_order(order2["id"], reserve_payload(v2), SA)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")


# ════════════════════════════════════════════════════════════════════════════
# Rule 6 — boundary_precision_check / special_order_deposit_capped_at_line_value
# ════════════════════════════════════════════════════════════════════════════
def test_special_order_deposit_capped_at_line_value():
    """PRD §3.8: "The required deposit is then the smaller of the line value
    itself and the larger of a flat minimum of 5000 cents and that percentage
    term; in other words the deposit is at least 5000 cents (subject to the
    line-value cap), but never exceeds the line value."

    Sku 4000, qty 1: max(5000, 1200)=5000 would exceed line_value 4000, so the
    cap pins deposit_required_cents=4000.

    Design: Difficulty/boundary_precision_check/special_order_deposit_capped_at_line_value
    """
    cust = create_customer()
    sku = create_sku(name="Bell", category="ACCESSORY", list_price_cents=4000, on_hand=0)
    so = validate_success(api_client.create_special_order(
        create_special_order_payload(cust["id"], sku["id"], 1), SA), 201)
    assert so["deposit_required_cents"] == 4000


def test_special_order_deposit_never_exceeds_line_value_other_qty():
    """PRD §3.8: "the deposit is at least 5000 cents (subject to the line-value
    cap), but never exceeds the line value."

    Sku 4000, qty 1, the deposit equals the line value 4000 (cap binds) rather
    than the 5000 minimum.

    Design: Difficulty/boundary_precision_check/special_order_deposit_capped_at_line_value
    """
    cust = create_customer()
    sku = create_sku(name="Bell B", category="ACCESSORY", list_price_cents=4000, on_hand=0)
    so = validate_success(api_client.create_special_order(
        create_special_order_payload(cust["id"], sku["id"], 1), SA), 201)
    assert so["deposit_required_cents"] == 4000
    assert so["deposit_required_cents"] <= sku["list_price_cents"] * 1


# ════════════════════════════════════════════════════════════════════════════
# Rule 8 — resource_temporal_overlap / bay_booking_half_open_overlap_vs_touching
# ════════════════════════════════════════════════════════════════════════════
def test_touching_bay_booking_is_allowed():
    """PRD §3.4: "because the intervals are half-open, a booking that starts
    precisely at an existing booking's `end_at` merely touches it with zero
    overlap and is therefore allowed."

    A 12:00-14:00 booking placed against an existing 10:00-12:00 booking is
    accepted (BOOKED).

    Design: Difficulty/resource_temporal_overlap/bay_booking_half_open_overlap_vs_touching
    """
    cust = create_customer()
    tier = create_tier(code="BASIC", base_labor_cents=8000, turnaround_hours=5)
    ticket = create_ticket(cust["id"], tier["id"])
    bay = create_bay(name="Bay 1")
    validate_success(api_client.create_bay_booking(create_bay_booking_payload(
        bay["id"], ticket["id"], "2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z"), ADV), 201)
    touching = validate_success(api_client.create_bay_booking(create_bay_booking_payload(
        bay["id"], ticket["id"], "2026-06-15T12:00:00Z", "2026-06-15T14:00:00Z"), ADV), 201)
    assert touching["status"] == "BOOKED"


def test_overlapping_bay_booking_rejected():
    """PRD §3.4: "A new booking is rejected with `ERR_BAY_DOUBLE_BOOKED` ... if
    it overlaps any existing `BOOKED` interval on the same bay. Two intervals
    overlap exactly when the existing start is before the new end and the new
    start is before the existing end".

    An 11:00-13:00 booking overlaps the existing 10:00-12:00 interval and is
    rejected with ERR_BAY_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/bay_booking_half_open_overlap_vs_touching
    """
    cust = create_customer()
    tier = create_tier(code="BASIC", base_labor_cents=8000, turnaround_hours=5)
    ticket = create_ticket(cust["id"], tier["id"])
    bay = create_bay(name="Bay 1")
    validate_success(api_client.create_bay_booking(create_bay_booking_payload(
        bay["id"], ticket["id"], "2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z"), ADV), 201)
    res = api_client.create_bay_booking(create_bay_booking_payload(
        bay["id"], ticket["id"], "2026-06-15T11:00:00Z", "2026-06-15T13:00:00Z"), ADV)
    validate_error(res, "ERR_BAY_DOUBLE_BOOKED")


# ════════════════════════════════════════════════════════════════════════════
# Rule 8 — resource_temporal_overlap / sku_aggregate_capacity_summed_lines_overlap
# ════════════════════════════════════════════════════════════════════════════
def test_summed_lines_exceed_stock_rejected():
    """PRD §3.5: "availability is evaluated over the summed quantity of all lines
    for the same `Sku` within the request, so two lines for the same product must
    be satisfiable together."

    Two qty-2 lines of the same Sku (summing to 4) against on_hand 3 are rejected
    with ERR_INSUFFICIENT_STOCK — the collision is over summed quantity.

    Design: Difficulty/resource_temporal_overlap/sku_aggregate_capacity_summed_lines_overlap
    """
    cust = create_customer()
    sku = create_sku(name="Inner Tube", category="PART", list_price_cents=1200, on_hand=3)
    order = create_order(cust["id"])
    add_order_line(order["id"], sku["id"], 2)
    add_order_line(order["id"], sku["id"], 2)
    v = get_sku(sku["id"])["version"]
    res = api_client.reserve_sales_order(order["id"], reserve_payload(v), SA)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")


def test_summed_lines_overflow_leaves_reserved_zero():
    """PRD §3.5: "If availability is insufficient the reserve fails with
    `ERR_INSUFFICIENT_STOCK`."
    PRD §2.6: "The `reserved` count is the sum of the `qty` of every
    `Reservation` row that points at this `Sku` and is currently in `ACTIVE`
    status".

    A rejected over-capacity reserve creates no reservations, so Sku.reserved
    stays 0.

    Design: Difficulty/resource_temporal_overlap/sku_aggregate_capacity_summed_lines_overlap
    """
    cust = create_customer()
    sku = create_sku(name="Inner Tube B", category="PART", list_price_cents=1200, on_hand=3)
    order = create_order(cust["id"])
    add_order_line(order["id"], sku["id"], 2)
    add_order_line(order["id"], sku["id"], 2)
    v = get_sku(sku["id"])["version"]
    res = api_client.reserve_sales_order(order["id"], reserve_payload(v), SA)
    assert res.status_code == 409
    sku_after = validate_success(api_client.get_sku(sku["id"], MGR), 200)
    assert sku_after["reserved"] == 0
