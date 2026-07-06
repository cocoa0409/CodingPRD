"""Catering orders: invoice rounding, the confirm guards, temporal overlap,
and terminal-state protection."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_catering_resource, setup_quoted_catering, setup_confirmed_catering,
    create_catering_order_payload,
)

MANAGER = TEST_USERS["manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def test_invoice_rounds_per_line_then_sums(api):
    """PRD §3.9: "for each line item, `line_cents` is `qty` multiplied by
    `unit_price_cents` multiplied by (one minus that line's `discount_pct`),
    rounded half up to whole cents; `invoice_total_cents` is the sum of those
    per-line amounts — each line is rounded first and only then summed."

    Design: Difficulty/combinatorial_formula/catering_invoice_round_per_line_then_sum
    """
    line_items = [
        {"qty": 1, "unit_price_cents": 251, "discount_pct": 0.60},
        {"qty": 1, "unit_price_cents": 251, "discount_pct": 0.60},
    ]
    _resource, order = setup_quoted_catering(api, line_items=line_items)
    assert order["invoice_total_cents"] == 200, \
        f"round-per-line (100+100) must total 200, not sum-then-round 201, got {order['invoice_total_cents']}"


def test_required_deposit_is_quarter_of_invoice(api):
    """PRD §3.9: "The `required_deposit_cents` is 25 percent of
    `invoice_total_cents`, rounded half up."

    Design: Difficulty/combinatorial_formula/catering_invoice_round_per_line_then_sum
    """
    line_items = [
        {"qty": 1, "unit_price_cents": 251, "discount_pct": 0.60},
        {"qty": 1, "unit_price_cents": 251, "discount_pct": 0.60},
    ]
    _resource, order = setup_quoted_catering(api, line_items=line_items)
    assert order["required_deposit_cents"] == 50, \
        f"required deposit must be 25% of 200 = 50, got {order['required_deposit_cents']}"
    assert order["status"] == "QUOTED"


def test_confirm_draft_state_error_beats_deposit(api):
    """PRD §2.7: "The global order is: first authentication
    (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then
    existence of every referenced resource (the `ERR_*_NOT_FOUND` family, HTTP
    404), then the target resource's state eligibility for the requested
    transition (HTTP 409), and only then the operation-specific business rules."
    PRD §3.9: "Confirming requires the order to be `QUOTED` (otherwise
    `ERR_CATERING_INVALID_STATE`)"

    Design: Difficulty/priority_pair_validation_conflict/catering_confirm_state_beats_deposit_fiscal
    """
    resource = make_catering_resource(api)
    order = validate_success(api.create_catering_order(
        create_catering_order_payload(resource["id"],
                                      [{"qty": 1, "unit_price_cents": 1000, "discount_pct": 0}]),
        CASHIER), expected_status=201)
    resp = api.confirm_catering_order(order["id"], 0, MANAGER)
    validate_error(resp, ApiErrorId.ERR_CATERING_INVALID_STATE.value)


def test_confirm_draft_rejected_leaves_order_draft(api):
    """PRD §3.9: "A new order's `status` is `DRAFT`, and its `invoice_total_cents`,
    `required_deposit_cents`, and `deposit_paid_cents` are respectively `null`,
    `null`, and 0 until it is quoted."

    Design: Difficulty/priority_pair_validation_conflict/catering_confirm_state_beats_deposit_fiscal
    """
    resource = make_catering_resource(api)
    order = validate_success(api.create_catering_order(
        create_catering_order_payload(resource["id"],
                                      [{"qty": 1, "unit_price_cents": 1000, "discount_pct": 0}]),
        CASHIER), expected_status=201)
    resp = api.confirm_catering_order(order["id"], 0, MANAGER)
    validate_error(resp, ApiErrorId.ERR_CATERING_INVALID_STATE.value)
    got = validate_success(api.get_catering_order(order["id"], CASHIER))
    assert got["status"] == "DRAFT", f"a rejected confirm must leave the order DRAFT, got {got['status']}"


def test_overlapping_booking_double_booked_rejected(api):
    """PRD §3.9: "the interval `[event_start, event_end)` must not overlap any
    other `CONFIRMED` or `FULFILLED` order on the same `resource_id` — the window
    is half-open, so two bookings that merely touch at an endpoint do not
    conflict, but any true overlap is rejected with `ERR_RESOURCE_DOUBLE_BOOKED`"

    Design: Difficulty/resource_temporal_overlap/catering_halfopen_overlap_rejected
    """
    resource, _order1 = setup_confirmed_catering(
        api, event_start="2026-03-02T10:00:00Z", event_end="2026-03-02T12:00:00Z",
        deposit_paid_cents=250)
    _r, order2 = setup_quoted_catering(
        api, resource=resource,
        event_start="2026-03-02T11:00:00Z", event_end="2026-03-02T13:00:00Z")
    resp = api.confirm_catering_order(order2["id"], 250, MANAGER)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_DOUBLE_BOOKED.value)
    got = validate_success(api.get_catering_order(order2["id"], CASHIER))
    assert got["status"] == "QUOTED", f"a double-booked confirm must leave the order QUOTED, got {got['status']}"


def test_touching_booking_endpoints_do_not_conflict(api):
    """PRD §3.9: "the interval `[event_start, event_end)` must not overlap any
    other `CONFIRMED` or `FULFILLED` order on the same `resource_id` — the window
    is half-open, so two bookings that merely touch at an endpoint do not
    conflict, but any true overlap is rejected with `ERR_RESOURCE_DOUBLE_BOOKED`"

    Design: Difficulty/resource_temporal_overlap/catering_halfopen_overlap_rejected
    """
    resource, _order1 = setup_confirmed_catering(
        api, event_start="2026-03-02T10:00:00Z", event_end="2026-03-02T12:00:00Z",
        deposit_paid_cents=250)
    _r, order2 = setup_quoted_catering(
        api, resource=resource,
        event_start="2026-03-02T12:00:00Z", event_end="2026-03-02T14:00:00Z")
    confirmed = validate_success(api.confirm_catering_order(order2["id"], 250, MANAGER))
    assert confirmed["status"] == "CONFIRMED", \
        f"a booking that merely touches at 12:00 must be allowed, got {confirmed['status']}"


def test_cancel_fulfilled_order_rejected(api):
    """PRD §3.9: "Cancelling requires the order to be in `DRAFT`, `QUOTED`, or
    `CONFIRMED` (otherwise `ERR_CATERING_INVALID_STATE`); cancelling a confirmed
    order frees its booking so the interval no longer blocks other confirmations."

    Design: Corner/state_machines/cancel_fulfilled_catering_rejected
    """
    _resource, order = setup_confirmed_catering(api, deposit_paid_cents=250)
    validate_success(api.fulfill_catering_order(order["id"], MANAGER))
    resp = api.cancel_catering_order(order["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_CATERING_INVALID_STATE.value)
    got = validate_success(api.get_catering_order(order["id"], CASHIER))
    assert got["status"] == "FULFILLED"


def test_confirm_insufficient_deposit_rejected(api):
    """PRD §3.9: "the recorded `deposit_paid_cents` must be at least
    `required_deposit_cents`, otherwise the confirmation is rejected with
    `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402)"

    Design: Corner/validations/catering_confirm_deposit_insufficient_when_state_ok
    """
    _resource, order = setup_quoted_catering(
        api, line_items=[{"qty": 1, "unit_price_cents": 1000, "discount_pct": 0}])
    resp = api.confirm_catering_order(order["id"], 0, MANAGER)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT.value)
    got = validate_success(api.get_catering_order(order["id"], CASHIER))
    assert got["status"] == "QUOTED", f"a deposit-rejected confirm must leave the order QUOTED, got {got['status']}"
