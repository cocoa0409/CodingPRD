"""Validation-ordering conflicts: when two business checks could both fire on one
request, the higher-priority error surfaces. Both pairs have explicit PRD-stated
ordering.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ensure_pricing_policy,
    create_cut_type,
    create_locker,
    create_customer,
    receive_lot,
    start_aging,
    set_clock,
    place_and_confirm_order,
    create_holiday_window,
    place_holiday_order,
    ApiErrorId,
    TEST_USERS,
)

MGR = TEST_USERS["shift_manager_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]
BUTCHER = TEST_USERS["butcher_headers"]


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / lot_not_available_outranks_insufficient_weight
# ===========================================================================
def test_lot_not_available_outranks_insufficient_weight(api):
    """PRD §3.5: "the lot must be `AVAILABLE` — drawing from a lot that is
    `AGING` ... is rejected with `ERR_LOT_NOT_AVAILABLE` (HTTP 409) ... the lot's
    `remaining_weight_g` must be at least the supplied `catch_weight_g`, or the
    draw is rejected with `ERR_INSUFFICIENT_LOT_WEIGHT` (HTTP 409)".

    Conditions "checked in order": AVAILABLE check precedes the weight check. A draw
    against an AGING lot for more grams than it holds -> ERR_LOT_NOT_AVAILABLE.

    Design: Difficulty/priority_pair_validation_conflict/lot_not_available_outranks_insufficient_weight
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="DRY_RIBEYE", species="BEEF",
                          base_price_cents_per_kg=6000, requires_dry_age=True)
    locker = create_locker(name="LOCKER-B", capacity_g=20000)
    cust = create_customer(full_name="Pat Priority", phone="555-0007")
    lot = receive_lot(cut["id"], received_weight_g=1000, aging_target_days=7)
    aged = start_aging(lot["id"], locker["id"])
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 5000)])
    resp = api.draw_line(
        line_ids[0],
        {"drawn_lot_id": lot["id"], "catch_weight_g": 5000,
         "expected_inventory_lot_version": aged["version"]},
        BUTCHER,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE.value)


def test_available_lot_insufficient_weight_surfaces_weight_error(api):
    """PRD §3.5: "the lot's `remaining_weight_g` must be at least the supplied
    `catch_weight_g`, or the draw is rejected with `ERR_INSUFFICIENT_LOT_WEIGHT`
    (HTTP 409)".

    When the lot IS available, the lower-priority weight check is the one that
    fires — confirming the ordering: 5000g drawn from a 1000g AVAILABLE lot ->
    ERR_INSUFFICIENT_LOT_WEIGHT.

    Design: Difficulty/priority_pair_validation_conflict/lot_not_available_outranks_insufficient_weight
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Polly Weight", phone="555-0070")
    lot = receive_lot(cut["id"], received_weight_g=1000)
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 5000)])
    resp = api.draw_line(
        line_ids[0],
        {"drawn_lot_id": lot["id"], "catch_weight_g": 5000,
         "expected_inventory_lot_version": lot["version"]},
        BUTCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_WEIGHT.value)


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / window_cutoff_outranks_holiday_capacity
# ===========================================================================
def test_window_cutoff_outranks_holiday_capacity(api):
    """PRD §3.6: "First, the timing gate: the current clock must be at or before
    the window's `cutoff_at`, or placement is rejected with
    `ERR_WINDOW_CUTOFF_PASSED` (HTTP 422). Second, the capacity gate: ... if the
    resulting committed total would exceed the window's `capacity_g`, placement is
    rejected with `ERR_HOLIDAY_CAPACITY_EXCEEDED` (HTTP 409)."

    A holiday order both past cutoff AND over capacity -> the first gate
    (ERR_WINDOW_CUTOFF_PASSED) surfaces.

    Design: Difficulty/priority_pair_validation_conflict/window_cutoff_outranks_holiday_capacity
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    window = create_holiday_window(name="THANKSGIVING_2026",
                                   pickup_date="2026-11-26T00:00:00Z",
                                   capacity_g=1000, cutoff_at="2026-11-20T00:00:00Z")
    cust = create_customer(full_name="Cole Cutoff", phone="555-0008")
    set_clock("2026-11-21T00:00:00Z")  # past cutoff
    resp = api.create_custom_order(
        {"customer_id": cust["id"], "order_kind": "HOLIDAY",
         "holiday_window_id": window["id"], "pickup_date": "2026-11-26T00:00:00Z",
         "lines": [{"cut_type_id": cut["id"], "ordered_weight_g": 5000}]},
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_CUTOFF_PASSED.value)


def test_holiday_capacity_fires_when_within_cutoff(api):
    """PRD §3.6: "if the resulting committed total would exceed the window's
    `capacity_g`, placement is rejected with `ERR_HOLIDAY_CAPACITY_EXCEEDED`
    (HTTP 409)."

    With the clock before cutoff, the lower-priority capacity gate is the one that
    fires for a 5000g order against a 1000g window — confirming the ordering.

    Design: Difficulty/priority_pair_validation_conflict/window_cutoff_outranks_holiday_capacity
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    set_clock("2026-11-19T00:00:00Z")  # before cutoff
    window = create_holiday_window(name="THANKSGIVING_2026B",
                                   pickup_date="2026-11-26T00:00:00Z",
                                   capacity_g=1000, cutoff_at="2026-11-20T00:00:00Z")
    cust = create_customer(full_name="Cara Capacity", phone="555-0088")
    resp = api.create_custom_order(
        {"customer_id": cust["id"], "order_kind": "HOLIDAY",
         "holiday_window_id": window["id"], "pickup_date": "2026-11-26T00:00:00Z",
         "lines": [{"cut_type_id": cut["id"], "ordered_weight_g": 5000}]},
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_HOLIDAY_CAPACITY_EXCEEDED.value)
