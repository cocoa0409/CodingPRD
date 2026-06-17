"""Warranty filing, coverage window, the approve-vs-deny branch, and gating.

The 90-day inclusive coverage boundary, the covered==false claim that may only be
denied, the approve-requires-covered precondition, and the not-completed filing gate.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_line_item_payload,
    create_completed_order, create_approved_order,
    get_work_order, factories,
    make_customer_headers,
    TEST_USERS,
)

CLERK = TEST_USERS["intake_clerk_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]


def _completed_repair_order(completed_at="2026-03-01T00:00:00Z"):
    return create_completed_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Touch-up", yardage_required=0, labor_hours=1)],
        deposit_amount_cents=2000,
        shop_day_date="2026-02-25",
        fulfillment_kind="PICKUP",
        fulfillment_window=("2026-02-28T09:00:00Z", "2026-02-28T11:00:00Z"),
        completed_at=completed_at,
    )


# ---------------------------------------------------------------------------
# Coverage boundary — exactly 90 days is covered (inclusive)
# ---------------------------------------------------------------------------
def test_warranty_exact_90th_day_is_covered(api):
    """PRD §3.9: "The claim is `covered` when the parent order is `COMPLETED` and that
    elapsed-day count is at most 90 days — a claim filed at exactly 90 days is still covered,
    while a claim filed on day 91 is not."

    Design: Difficulty/boundary_precision_check/warranty_exact_90th_day_is_covered_inclusive
    """
    cust, wo = _completed_repair_order(completed_at="2026-03-01T00:00:00Z")
    res = api.file_warranty_claim(
        wo["id"], factories.file_warranty_claim_payload("2026-05-30T00:00:00Z", defect_note="fade"),
        make_customer_headers(cust["id"]))
    claim = validate_success(res, 201)
    assert claim["covered"] is True


def test_warranty_day_91_is_not_covered(api):
    """PRD §3.9: "The claim is `covered` when the parent order is `COMPLETED` and that
    elapsed-day count is at most 90 days — a claim filed at exactly 90 days is still covered,
    while a claim filed on day 91 is not."

    Design: Difficulty/boundary_precision_check/warranty_exact_90th_day_is_covered_inclusive
    """
    cust, wo = _completed_repair_order(completed_at="2026-03-01T00:00:00Z")
    res = api.file_warranty_claim(
        wo["id"], factories.file_warranty_claim_payload("2026-05-31T00:00:00Z", defect_note="late fade"),
        make_customer_headers(cust["id"]))
    claim = validate_success(res, 201)
    assert claim["covered"] is False  # 2026-03-01 -> 2026-05-31 is 91 days


# ---------------------------------------------------------------------------
# Branch: out-of-window claim (covered==false) can only be DENIED
# ---------------------------------------------------------------------------
def test_out_of_window_claim_is_not_covered_and_can_be_denied(api):
    """PRD §3.9: "The claim is `covered` when the parent order is `COMPLETED` and that
    elapsed-day count is at most 90 days — a claim filed at exactly 90 days is still covered,
    while a claim filed on day 91 is not."
    PRD §3.9: "An `OPEN` claim may instead be denied, moving it to `DENIED`, regardless of
    coverage."

    Design: Difficulty/non_linear_state_machine/warrantyclaim_branching_approve_vs_deny
    """
    cust, wo = _completed_repair_order(completed_at="2026-03-01T00:00:00Z")
    claim = validate_success(api.file_warranty_claim(
        wo["id"], factories.file_warranty_claim_payload("2026-05-31T00:00:00Z", defect_note="seam split"),
        make_customer_headers(cust["id"])), 201)
    assert claim["covered"] is False
    denied = validate_success(api.deny_warranty_claim(claim["id"], MANAGER), 200)
    assert denied["status"] == "DENIED"


def test_covered_claim_can_be_approved(api):
    """PRD §3.9: "An `OPEN` claim may be approved only when its `covered` flag is true,
    moving it to `APPROVED`."

    Design: Difficulty/non_linear_state_machine/warrantyclaim_branching_approve_vs_deny
    """
    cust, wo = _completed_repair_order(completed_at="2026-03-01T00:00:00Z")
    claim = validate_success(api.file_warranty_claim(
        wo["id"], factories.file_warranty_claim_payload("2026-05-30T00:00:00Z", defect_note="fade"),
        make_customer_headers(cust["id"])), 201)
    assert claim["covered"] is True
    approved = validate_success(api.approve_warranty_claim(claim["id"], MANAGER), 200)
    assert approved["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Approve requires covered==true
# ---------------------------------------------------------------------------
def test_warranty_approve_requires_covered_true(api):
    """PRD §3.9: "an attempt to approve a claim whose `covered` flag is false is rejected
    with `ERR_INVALID_STATE`, so an out-of-window claim can only ever be denied."

    Design: Corner/state_machines/warranty_approve_requires_covered_true
    """
    cust, wo = _completed_repair_order(completed_at="2026-03-01T00:00:00Z")
    claim = validate_success(api.file_warranty_claim(
        wo["id"], factories.file_warranty_claim_payload("2026-05-31T00:00:00Z", defect_note="late defect"),
        make_customer_headers(cust["id"])), 201)
    assert claim["covered"] is False
    res = api.approve_warranty_claim(claim["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    got = validate_success(api.get_warranty_claim(claim["id"], MANAGER), 200)
    assert got["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Filing gate — order must be COMPLETED
# ---------------------------------------------------------------------------
def test_warranty_claim_on_non_completed_order_returns_error(api):
    """PRD §3.9: "Only the owning customer may file a warranty claim, and only against a
    `COMPLETED` order; filing against any other status is rejected with
    `ERR_ORDER_NOT_COMPLETED`."

    Design: Corner/validations/warranty_claim_on_non_completed_order_returns_error
    """
    cust, wo, _, _ = create_approved_order(
        service_type="REPAIR", deposit_amount_cents=2000,
        line_items=[create_line_item_payload(piece_label="P", yardage_required=0, labor_hours=1)],
    )
    res = api.file_warranty_claim(
        wo["id"], factories.file_warranty_claim_payload("2026-06-15T00:00:00Z", defect_note="premature"),
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_ORDER_NOT_COMPLETED", expected_status=409)
