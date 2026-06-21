"""Holiday windows: capacity boundary inclusivity, the capacity-exceeded gate, and
the immediate-consistency deposit/committed visibility.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ensure_pricing_policy,
    create_cut_type,
    create_customer,
    create_holiday_window,
    set_clock,
    setup_holiday_window_before_cutoff,
    place_holiday_order,
    ApiErrorId,
    TEST_USERS,
)

MGR = TEST_USERS["shift_manager_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]


# ===========================================================================
# Difficulty: boundary_precision_check / holiday_capacity_inclusive_at_equality
# ===========================================================================
def test_holiday_capacity_accepted_at_exact_equality(api):
    """PRD §3.6: "The boundary is inclusive at equality: a placement that brings
    `committed_g` to exactly `capacity_g` is accepted, and only a placement that
    would push it strictly above `capacity_g` is rejected."

    Capacity 10000, 5000 already committed, a second 5000 -> committed exactly
    10000 -> accepted (order PLACED).

    Design: Difficulty/boundary_precision_check/holiday_capacity_inclusive_at_equality
    """
    setup = setup_holiday_window_before_cutoff(capacity_g=10000)
    cut, window = setup["cut_type"], setup["window"]
    a = create_customer(full_name="Ann First", phone="555-0009")
    place_holiday_order(a["id"], window["id"], [(cut["id"], 5000)])
    b = create_customer(full_name="Bob Second", phone="555-0010")
    order = place_holiday_order(b["id"], window["id"], [(cut["id"], 5000)])
    assert order["order_status"] == "PLACED"

    win_after = get_success_data(api.get_holiday_window(window["id"], MGR))
    assert win_after["committed_g"] == 10000, (
        f"committed_g should be exactly 10000, got {win_after['committed_g']}"
    )


def test_holiday_capacity_rejected_one_gram_over(api):
    """PRD §3.6: "only a placement that would push it strictly above `capacity_g`
    is rejected."
    PRD §3.6: "if the resulting committed total would exceed the window's
    `capacity_g`, placement is rejected with `ERR_HOLIDAY_CAPACITY_EXCEEDED`
    (HTTP 409)."

    Capacity 10000, 5000 already committed, a 5001 order -> 10001 > 10000 ->
    rejected.

    Design: Difficulty/boundary_precision_check/holiday_capacity_inclusive_at_equality
    """
    setup = setup_holiday_window_before_cutoff(capacity_g=10000)
    cut, window = setup["cut_type"], setup["window"]
    a = create_customer(full_name="Ann First", phone="555-0091")
    place_holiday_order(a["id"], window["id"], [(cut["id"], 5000)])
    b = create_customer(full_name="Otto Over", phone="555-0092")
    resp = api.create_custom_order(
        {"customer_id": b["id"], "order_kind": "HOLIDAY",
         "holiday_window_id": window["id"], "pickup_date": "2026-11-26T00:00:00Z",
         "lines": [{"cut_type_id": cut["id"], "ordered_weight_g": 5001}]},
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_HOLIDAY_CAPACITY_EXCEEDED.value)


# ===========================================================================
# Corner: validations / holiday_capacity_exceeded_when_over
# ===========================================================================
def test_holiday_capacity_exceeded_corner(api):
    """PRD §3.6: "The order's own ordered grams — the sum of `ordered_weight_g`
    over its lines — are added; if the resulting committed total would exceed the
    window's `capacity_g`, placement is rejected with
    `ERR_HOLIDAY_CAPACITY_EXCEEDED` (HTTP 409)."

    Capacity 10000 with 5000 committed; a 5001 order pushes committed to 10001 ->
    rejected.

    Design: Corner/validations/holiday_capacity_exceeded_when_over
    """
    setup = setup_holiday_window_before_cutoff(capacity_g=10000)
    cut, window = setup["cut_type"], setup["window"]
    under = create_customer(full_name="Ulla Under", phone="555-1009")
    place_holiday_order(under["id"], window["id"], [(cut["id"], 5000)])
    over = create_customer(full_name="Otto Over", phone="555-1010")
    resp = api.create_custom_order(
        {"customer_id": over["id"], "order_kind": "HOLIDAY",
         "holiday_window_id": window["id"], "pickup_date": "2026-11-26T00:00:00Z",
         "lines": [{"cut_type_id": cut["id"], "ordered_weight_g": 5001}]},
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_HOLIDAY_CAPACITY_EXCEEDED.value)


# ===========================================================================
# Corner: consistency_model / holiday_deposit_charged_and_visible_same_request
# ===========================================================================
def test_holiday_deposit_and_committed_visible_immediately(api):
    """PRD §3.6: "On holiday placement the server sets the order's `deposit_cents`
    to one quarter of the order's `estimated_total_cents`".
    PRD §3.6: "When the order is accepted, the window's `committed_g` is recomputed
    to include it".

    A 2000g RIBEYE holiday order (estimate 8000) shows deposit_cents 2000 on the
    placement response, and a same-instant GET of the window shows committed_g 2000.

    Design: Corner/consistency_model/holiday_deposit_charged_and_visible_same_request
    """
    setup = setup_holiday_window_before_cutoff(capacity_g=100000)
    cut, window = setup["cut_type"], setup["window"]
    cust = create_customer(full_name="Cora Commit", phone="555-1018")
    order = place_holiday_order(cust["id"], window["id"], [(cut["id"], 2000)])
    assert order["deposit_cents"] == 2000
    win_after = get_success_data(api.get_holiday_window(window["id"], MGR))
    assert win_after["committed_g"] == 2000, (
        f"committed_g should be visible as 2000 immediately, got {win_after['committed_g']}"
    )
