"""Single-failure business validations and 1099-K threshold issuance.

Translates queue A (Difficulty) boundary_precision_check (federal threshold) and
queue B (Corner) validations / calculations instances. Each validation is tested
in an isolated scenario where only one check can fail.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_fee_schedule, create_seller, create_order,
    onboard_active_seller,
    create_requested_refund, apply_refund,
    seller_with_settled_gross,
    set_clock,
    make_seller_headers,
)
from test_helpers import api_client


# ─────────────────────────────────────────────────────────────────────────────
# boundary_precision_check / tax_form_gross_at_5000_threshold_inclusive_federal
# ─────────────────────────────────────────────────────────────────────────────

def test_tax_form_gross_exactly_5000_threshold_inclusive_federal(api, finance_headers):
    """PRD §3.11: "The form's `threshold_basis` is then selected by inclusive
    thresholds: if the reported gross is at least five hundred thousand cents (five
    thousand dollars), the basis is `FEDERAL_5000`".
    PRD §3.11: "Issuing the form computes its figures and moves `form_status` from
    `DRAFT` to `ISSUED`."

    Design: Difficulty/boundary_precision_check/tax_form_gross_at_5000_threshold_inclusive_federal
    """
    # 5 orders of 100000 = exactly 500000 gross, all matured AVAILABLE in 2026.
    seller, orders, form = seller_with_settled_gross(
        total_gross=500000, num_orders=5, tax_year=2026,
        settle_iso="2026-01-15T00:00:00Z", mature_iso="2026-01-25T00:00:00Z",
    )
    issued = validate_success(api.issue_tax_form(form["id"], {}, finance_headers), 200)
    assert issued["gross_reported_cents"] == 500000
    assert issued["threshold_basis"] == "FEDERAL_5000"
    assert issued["form_status"] == "ISSUED"


def test_tax_form_gross_one_below_5000_threshold_blocked(api, finance_headers):
    """PRD §3.11: "if the reported gross is at least five hundred thousand cents ...
    the basis is `FEDERAL_5000`; otherwise ... the basis is `NONE`."
    PRD §3.11: "Issuing a form whose computed `threshold_basis` is `NONE` is a
    below-threshold form and is blocked unless the request supplies `force` as true;
    a blocked issuance returns `ERR_BELOW_1099K_THRESHOLD` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/tax_form_gross_at_5000_threshold_inclusive_federal
    """
    # 499999 (one below the inclusive 500000 federal boundary) → basis NONE → blocked.
    seller, orders, form = seller_with_settled_gross(
        total_gross=499999, num_orders=1, tax_year=2026,
        settle_iso="2026-01-15T00:00:00Z", mature_iso="2026-01-25T00:00:00Z",
    )
    res = api.issue_tax_form(form["id"], {}, finance_headers)
    validate_error(res, "ERR_BELOW_1099K_THRESHOLD", expected_status=422)
    refetched = validate_success(api.get_tax_form(form["id"], finance_headers), 200)
    assert refetched["form_status"] == "DRAFT"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations — below-threshold issuance blocked
# ─────────────────────────────────────────────────────────────────────────────

def test_form_1099k_below_threshold_basis_none_blocked(api, finance_headers):
    """PRD §3.11: "Issuing a form whose computed `threshold_basis` is `NONE` is a
    below-threshold form and is blocked unless the request supplies `force` as true;
    a blocked issuance returns `ERR_BELOW_1099K_THRESHOLD` (HTTP 422)."

    Design: Corner/calculations/form_1099k_below_threshold_basis_none
    """
    seller, orders, form = seller_with_settled_gross(
        total_gross=499900, num_orders=1, tax_year=2026,
        settle_iso="2026-01-05T00:00:00Z", mature_iso="2026-01-15T00:00:00Z",
    )
    res = api.issue_tax_form(form["id"], {}, finance_headers)
    validate_error(res, "ERR_BELOW_1099K_THRESHOLD", expected_status=422)
    refetched = validate_success(api.get_tax_form(form["id"], finance_headers), 200)
    assert refetched["form_status"] == "DRAFT"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / validations
# ─────────────────────────────────────────────────────────────────────────────

def test_refund_exceeds_remaining_returns_422(api, finance_headers):
    """PRD §3.6: "A refund that would exceed the remaining unrefunded gross is
    rejected with `ERR_REFUND_EXCEEDS_REMAINING` (HTTP 422)".

    Design: Corner/validations/refund_exceeds_remaining_returns_422
    """
    set_clock("2026-01-10T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    # Single refund of 12000 exceeds remaining 10000.
    refund = create_requested_refund(order["id"], refund_amount_cents=12000)
    res = api.apply_refund(refund["id"], finance_headers)
    validate_error(res, "ERR_REFUND_EXCEEDS_REMAINING", expected_status=422)


def test_refund_on_already_clawed_order_returns_409(api, finance_headers):
    """PRD §3.6: "an attempt to apply against an already-clawed order is rejected with
    `ERR_ORDER_ALREADY_CLAWED` (HTTP 409)."

    Design: Corner/validations/refund_on_already_clawed_order_returns_409
    """
    # First refund 3000 APPLIED → order REFUND_CLAWED, remaining 7000.
    # Second refund 2000 (within remaining, so the ceiling check cannot fire) →
    # only the already-clawed guard applies.
    set_clock("2026-01-10T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    r1 = create_requested_refund(order["id"], refund_amount_cents=3000)
    apply_refund(r1["id"])
    r2 = create_requested_refund(order["id"], refund_amount_cents=2000)
    res = api.apply_refund(r2["id"], finance_headers)
    validate_error(res, "ERR_ORDER_ALREADY_CLAWED", expected_status=409)


def test_close_seller_with_open_balance_returns_409(api, reviewer_headers, finance_headers):
    """PRD §3.2: "An attempt to close a seller while any order's settlement is still
    `PENDING` or `AVAILABLE` is rejected with `ERR_OPEN_BALANCE_BLOCKS_CLOSE`
    (HTTP 409)."

    Design: Corner/validations/close_seller_with_open_balance_returns_409
    """
    set_clock("2026-01-10T00:00:00Z")
    seller, _pm = onboard_active_seller()
    # One PENDING order blocks the close.
    create_order(seller["id"], gross_amount_cents=10000)
    res = api.close_seller(seller["id"], reviewer_headers)
    validate_error(res, "ERR_OPEN_BALANCE_BLOCKS_CLOSE", expected_status=409)
    refetched = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    assert refetched["account_status"] == "ACTIVE"
