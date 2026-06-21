"""Returns, refunds, the return window, and protection plans — the refund
calculation, the depth-3 refund cascade, the revert path, the category-dependent
window with its inclusive boundary, and protection eligibility.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, TEST_USERS,
    create_customer, create_sofa_product, create_draft_order, add_line, pay_in_full,
    confirm, create_route, book_stop, deliver_order, file_return,
    setup_delivered_order, setup_approved_return,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]
DD = TEST_USERS["dispatcher_headers"]


# ─── Difficulty: return refund dual variant ───────────────────────────────
def test_damaged_return_full_refund_zero_restock(api):
    """PRD 3.10: "When the `reason` is `DAMAGED` or `DEFECTIVE`, the `restocking_fee_cents`
    is 0 ... The `refund_amount_cents` is the gross minus the restocking fee."

    line_total 100000, DAMAGED -> restocking 0, refund 100000.

    Design: Difficulty/dual_variant_calc/return_refund_damaged_zero_restock_vs_changed_mind_restock
    """
    customer, product, order, line, ret = setup_approved_return(reason="DAMAGED")
    assert ret["status"] == "APPROVED"
    assert ret["restocking_fee_cents"] == 0
    assert ret["refund_amount_cents"] == 100000


def test_changed_mind_return_withholds_restock(api):
    """PRD 3.10: "when the `reason` is `CHANGED_MIND`, the `restocking_fee_cents` is the
    gross multiplied by 1,500 basis points (that is, by 1,500 divided by 10,000), rounded
    half-up to whole cents. The `refund_amount_cents` is the gross minus the restocking
    fee."

    line_total 100000, CHANGED_MIND -> restocking 15000, refund 85000.

    Design: Difficulty/dual_variant_calc/return_refund_damaged_zero_restock_vs_changed_mind_restock
    """
    customer, product, order, line, ret = setup_approved_return(reason="CHANGED_MIND")
    assert ret["status"] == "APPROVED"
    assert ret["restocking_fee_cents"] == 15000
    assert ret["refund_amount_cents"] == 85000


# ─── Difficulty: refund cascade depth-3 ───────────────────────────────────
def test_refund_cascade_line_returned_protection_voided(api):
    """PRD 3.10: "the covered line's `status` is set to `RETURNED`, that line's protection
    plan (if it is `ACTIVE`) is moved to `VOIDED`, the order's `amount_refunded_cents` is
    increased by this request's `refund_amount_cents` ..."

    refund -> line RETURNED -> its ACTIVE PREMIUM plan VOIDED; order ledger += 85000.

    Design: Difficulty/transitive_cascade/refund_cascades_line_returned_then_protection_voided_depth3
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T09:00:00Z"}, SM))
    product = get_success_data(api.create_product({
        "sku": "SOFA-STD", "name": "Aspen Sofa", "category": "SOFA",
        "base_price_cents": 100000,
        "available_fabrics": [{"code": "STANDARD", "surcharge_cents": 0}],
        "available_sizes": [{"code": "STD", "surcharge_cents": 0}],
        "protection_eligible": True}, SM))
    customer = create_customer()
    order = create_draft_order(customer["id"])
    line = add_line(order["id"], product["id"])
    pp = get_success_data(api.create_protection_plan(
        {"order_line_id": line["id"], "tier": "PREMIUM", "coverage_years": 3}, SA))
    pay_in_full(order["id"])
    confirm(order["id"])
    deliver_order(order["id"])
    ret = file_return(line["id"], customer["id"], reason="CHANGED_MIND")
    get_success_data(api.approve_return_request(ret["id"], SM))

    refunded = validate_success(api.refund_return_request(ret["id"], SM), 200)
    assert refunded["status"] == "REFUNDED"
    line_after = get_success_data(api.get_order_line(line["id"], SA))
    assert line_after["status"] == "RETURNED", "covered line flips to RETURNED"
    pp_after = get_success_data(api.get_protection_plan(pp["id"], SA))
    assert pp_after["status"] == "VOIDED", "line's protection plan voided by the cascade"
    order_after = get_success_data(api.get_order(order["id"], SA))
    assert order_after["amount_refunded_cents"] == 85000


def test_refund_advances_order_refund_ledger(api):
    """PRD 2.8: "Refunding a return marks the covered line returned, voids that line's
    active protection plan, and advances the order's refund ledger."

    Second test for this depth-3 chain: the ledger increment is visible on the order
    immediately after refund (a CHANGED_MIND refund of 85000).

    Design: Difficulty/transitive_cascade/refund_cascades_line_returned_then_protection_voided_depth3
    """
    customer, product, order, line, ret = setup_approved_return(reason="CHANGED_MIND")
    before = get_success_data(api.get_order(order["id"], SA))
    assert before["amount_refunded_cents"] == 0
    get_success_data(api.refund_return_request(ret["id"], SM))
    after = get_success_data(api.get_order(order["id"], SA))
    assert after["amount_refunded_cents"] == 85000


# ─── Difficulty: return-window inclusive boundary ─────────────────────────
def test_return_window_exact_deadline_passes(api):
    """PRD 3.10: "the gate passes when filed_on is on or before that deadline, with the
    boundary inclusive (a filing exactly on the deadline still passes)."

    Standard sofa delivered 2026-03-01, deadline 2026-03-31 (30 days); filed exactly
    2026-03-31 PASSES.

    Design: Difficulty/boundary_precision_check/return_window_inclusive_boundary_exact_deadline_passes
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T09:00:00Z"}, SM))
    customer, product, order, line, route, stop = setup_delivered_order()
    get_success_data(api.set_clock({"to_iso8601": "2026-03-31T12:00:00Z"}, SM))
    ret = file_return(line["id"], customer["id"], reason="CHANGED_MIND")
    approved = validate_success(api.approve_return_request(ret["id"], SM), 200)
    assert approved["status"] == "APPROVED", "filing on the deadline day is inclusive"


def test_return_window_day_before_deadline_passes(api):
    """PRD 3.10: "the gate passes when filed_on is on or before that deadline, with the
    boundary inclusive (a filing exactly on the deadline still passes)."

    Second test for this boundary instance: one day inside the window (2026-03-30,
    deadline 2026-03-31) also passes, pinning the inclusive `<=` from below.

    Design: Difficulty/boundary_precision_check/return_window_inclusive_boundary_exact_deadline_passes
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T09:00:00Z"}, SM))
    customer, product, order, line, route, stop = setup_delivered_order()
    get_success_data(api.set_clock({"to_iso8601": "2026-03-30T12:00:00Z"}, SM))
    ret = file_return(line["id"], customer["id"], reason="CHANGED_MIND")
    approved = validate_success(api.approve_return_request(ret["id"], SM), 200)
    assert approved["status"] == "APPROVED", "filing one day before the deadline passes"


def test_return_window_after_deadline_closed(api):
    """PRD 3.10: "A late filing is rejected with `ERR_RETURN_WINDOW_CLOSED`."

    Standard sofa delivered 2026-03-01, deadline 2026-03-31; filed 2026-04-15 (45 days,
    past the boundary) is rejected.

    Design: Corner/calculations/return_window_closed_after_deadline
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T09:00:00Z"}, SM))
    customer, product, order, line, route, stop = setup_delivered_order()
    get_success_data(api.set_clock({"to_iso8601": "2026-04-15T12:00:00Z"}, SM))
    ret = file_return(line["id"], customer["id"], reason="CHANGED_MIND")
    res = api.approve_return_request(ret["id"], SM)
    validate_error(res, "ERR_RETURN_WINDOW_CLOSED")


# ─── Corner: mattress 100-day window ──────────────────────────────────────
def test_mattress_return_within_100_day_window_approves(api):
    """PRD 3.10: "The window deadline is the line's delivery date advanced by a
    category-dependent number of days — 100 days when the covered product's `category` is
    `MATTRESS`, and 30 days otherwise ..."

    A mattress delivered 2026-03-01, return filed 2026-05-01 (61 days) is inside the
    100-day window and APPROVES.

    Design: Corner/calculations/mattress_return_window_100_days_vs_standard_30
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T09:00:00Z"}, SM))
    mattress = get_success_data(api.create_product({
        "sku": "MATT-Q", "name": "Queen Mattress", "category": "MATTRESS",
        "base_price_cents": 80000,
        "available_fabrics": [{"code": "STANDARD", "surcharge_cents": 0}],
        "available_sizes": [{"code": "QUEEN", "surcharge_cents": 0}]}, SM))
    customer = create_customer()
    order = create_draft_order(customer["id"])
    line = add_line(order["id"], mattress["id"], fabric_code="STANDARD", size_code="QUEEN")
    pay_in_full(order["id"])
    confirm(order["id"])
    deliver_order(order["id"])
    get_success_data(api.set_clock({"to_iso8601": "2026-05-01T12:00:00Z"}, SM))
    ret = file_return(line["id"], customer["id"], reason="CHANGED_MIND")
    approved = validate_success(api.approve_return_request(ret["id"], SM), 200)
    assert approved["status"] == "APPROVED", "61 days is within the 100-day mattress window"


# ─── Corner: reject an approved return (revert path) ──────────────────────
def test_reject_approved_return_no_ledger_drift(api):
    """PRD 3.10: "an `APPROVED → REJECTED` rejection is a revert path that may be taken
    before any refund is disbursed and fires no ledger or line side effects."

    Design: Corner/state_machines/reject_approved_return_revert_no_ledger_drift
    """
    customer, product, order, line, ret = setup_approved_return(reason="CHANGED_MIND")
    rejected = validate_success(api.reject_return_request(ret["id"], SM), 200)
    assert rejected["status"] == "REJECTED"
    order_after = get_success_data(api.get_order(order["id"], SA))
    assert order_after["amount_refunded_cents"] == 0, "no ledger drift on revert"
    line_after = get_success_data(api.get_order_line(line["id"], SA))
    assert line_after["status"] == "ACTIVE", "line stays ACTIVE on revert"


# ─── Corner: protection on ineligible product ─────────────────────────────
def test_protection_on_ineligible_product_rejected(api):
    """PRD 3.7: "A protection plan may be attached only to a line whose product has
    `protection_eligible` set to true and that does not already carry an active plan ...
    a violation of either condition is rejected with `ERR_PROTECTION_NOT_ALLOWED`."

    Design: Corner/validations/protection_on_ineligible_product_returns_not_allowed
    """
    table = get_success_data(api.create_product({
        "sku": "TABLE-NP", "name": "Glass Table", "category": "TABLE",
        "base_price_cents": 50000,
        "available_fabrics": [{"code": "STANDARD", "surcharge_cents": 0}],
        "available_sizes": [{"code": "STD", "surcharge_cents": 0}],
        "protection_eligible": False}, SM))
    customer = create_customer()
    order = create_draft_order(customer["id"])
    line = add_line(order["id"], table["id"])
    res = api.create_protection_plan(
        {"order_line_id": line["id"], "tier": "BASIC", "coverage_years": 1}, SA)
    validate_error(res, "ERR_PROTECTION_NOT_ALLOWED")
