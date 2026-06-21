"""Validation precedence (state-check beats size-standard; period-order beats
principal-overpay) and cross-entity state dependencies (credit-memo submit gated on
FormPackage CLEARED; guaranty-sale settle gated on Application AUTHORIZED+).

Covers difficulty rules priority_pair_validation_conflict and
cross_entity_state_dependency.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_draft_application, create_underwriting_application,
    reach_fully_disbursed, reach_approved,
    file_servicing_report,
    add_collateral, author_credit_memo,
    offer_guaranty_sale,
    TEST_USERS,
)
from test_helpers.api_client import api_client

OFFICER = TEST_USERS["loan_officer_headers"]
APPROVER = TEST_USERS["credit_approver_headers"]
SBA = TEST_USERS["sba_officer_headers"]
INVESTOR = TEST_USERS["investor_servicer_headers"]


# ─── priority_pair: authorize state check beats size standard ─────────────────

def test_authorize_unapproved_size_ineligible_returns_invalid_state(api):
    """PRD §2.10: "for a state-transition endpoint, the target resource must currently be in a state from which the transition is legal (`ERR_INVALID_STATE`, HTTP 409). Only after all of these pass does the system evaluate the domain-specific business rules described in §3, each of which carries its own error identifier."
    PRD §3.6: "Authorization re-checks that `size_eligible` is true, rejecting with `ERR_SIZE_STANDARD_EXCEEDED` otherwise."

    Design: Difficulty/priority_pair_validation_conflict/authorize_state_beats_size_standard
    """
    # Borrower size-INELIGIBLE (tnw/ni/emp all over caps); application never submitted, so it
    # stays DRAFT. Authorizing out of order hits the state check (ERR_INVALID_STATE) before the
    # size-standard business rule.
    ctx = create_draft_application(
        borrower_overrides={
            "tangible_net_worth_cents": 2_000_000_001,
            "avg_net_income_cents": 650_000_001,
            "affiliate_employee_count": 501,
        })
    aid = ctx["application"]["id"]
    res = api.authorize_application(aid, SBA)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_authorize_from_draft_does_not_return_size_error(api):
    """PRD §2.10: "Only after all of these pass does the system evaluate the domain-specific
    business rules described in §3".

    Design: Difficulty/priority_pair_validation_conflict/authorize_state_beats_size_standard
    """
    # Same out-of-order authorize: confirm the error is the state error, not the size error.
    ctx = create_draft_application(
        borrower_overrides={
            "tangible_net_worth_cents": 2_000_000_001,
            "avg_net_income_cents": 650_000_001,
            "affiliate_employee_count": 501,
        })
    aid = ctx["application"]["id"]
    res = api.authorize_application(aid, SBA)
    body = res.json()["data"]
    assert body["error_id"] == ApiErrorId.ERR_INVALID_STATE.value
    assert body["error_id"] != ApiErrorId.ERR_SIZE_STANDARD_EXCEEDED.value


# ─── priority_pair: servicing period order beats principal overpay ────────────

def test_servicing_accept_period_gap_and_overpay_returns_period_error(api):
    """PRD §3.9: "Acceptance is guarded by two preconditions. First, the report's closed interval must be contiguous with and non-overlapping with the prior accepted interval: its `period_start_month` must equal one plus the largest `period_end_month` among already-accepted reports on the application, or 0 if this is the first accepted report; otherwise the accept is rejected with `ERR_PERIOD_OUT_OF_ORDER`. Second, the reported `principal_paid_cents` must not exceed the application's current `outstanding_principal_cents`, or the accept is rejected with `ERR_PRINCIPAL_OVERPAY`."

    Design: Difficulty/priority_pair_validation_conflict/servicing_period_order_beats_principal_overpay
    """
    # First report ever, but it starts at month 3 (expected 0) AND principal 99000000 >
    # outstanding 50000000. The "First ... Second" ordering in §3.9 makes the period check win.
    ctx = reach_fully_disbursed()
    aid = ctx["application"]["id"]
    rpt = file_servicing_report(aid, 3, 3, principal_paid_cents=99_000_000, days_past_due=0,
                                period_index=3)
    res = api.accept_servicing_report(rpt["id"], SBA)
    validate_error(res, ApiErrorId.ERR_PERIOD_OUT_OF_ORDER.value)
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["outstanding_principal_cents"] == 50_000_000


def test_servicing_accept_period_gap_does_not_return_overpay(api):
    """PRD §3.9: "First, the report's closed interval must be contiguous with and non-overlapping with the prior accepted interval: its `period_start_month` must equal one plus the largest `period_end_month` among already-accepted reports on the application, or 0 if this is the first accepted report; otherwise the accept is rejected with `ERR_PERIOD_OUT_OF_ORDER`."
    PRD §3.9: "Second, the reported `principal_paid_cents` must not exceed the application's current `outstanding_principal_cents`, or the accept is rejected with `ERR_PRINCIPAL_OVERPAY`."

    Design: Difficulty/priority_pair_validation_conflict/servicing_period_order_beats_principal_overpay
    """
    ctx = reach_fully_disbursed()
    aid = ctx["application"]["id"]
    rpt = file_servicing_report(aid, 3, 3, principal_paid_cents=99_000_000, days_past_due=0,
                                period_index=3)
    res = api.accept_servicing_report(rpt["id"], SBA)
    body = res.json()["data"]
    assert body["error_id"] == ApiErrorId.ERR_PERIOD_OUT_OF_ORDER.value
    assert body["error_id"] != ApiErrorId.ERR_PRINCIPAL_OVERPAY.value


# ─── cross_entity_state_dependency: credit-memo submit requires CLEARED package ─

def test_credit_memo_submit_blocked_when_form_package_flagged(api):
    """PRD §3.4: "the application's form package must be in `CLEARED` status, or the submit is rejected with `ERR_FORM_PACKAGE_NOT_CLEARED`".

    Design: Difficulty/cross_entity_state_dependency/credit_memo_submit_requires_form_package_cleared
    """
    # UNDERWRITING loan whose FormPackage was reviewed with character_cleared=false -> FLAGGED.
    ctx = create_underwriting_application()
    aid = ctx["application"]["id"]
    add_collateral(aid, asset_type="REAL_ESTATE", appraised_value_cents=70_000_000)
    fp = validate_success(api.create_form_package(
        {"application_id": aid, "form_1919_complete": True, "form_1920_complete": True,
         "character_cleared": False}, OFFICER), 201)
    validate_success(api.submit_form_package(fp["id"], OFFICER), 200)
    validate_success(api.review_form_package(fp["id"], APPROVER), 200)  # -> FLAGGED
    memo = author_credit_memo(aid, recommendation="APPROVE")
    res = api.submit_credit_memo(memo["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_FORM_PACKAGE_NOT_CLEARED.value)
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["status"] == "UNDERWRITING"


def test_credit_memo_stays_draft_when_form_package_flagged(api):
    """PRD §3.4: "Submitting the credit memo advances the memo from `DRAFT` to `SUBMITTED` and the application's `status` from `UNDERWRITING` to `PENDING_APPROVAL`."
    PRD §3.4: "the application's form package must be in `CLEARED` status, or the submit is rejected with `ERR_FORM_PACKAGE_NOT_CLEARED`".

    Design: Difficulty/cross_entity_state_dependency/credit_memo_submit_requires_form_package_cleared
    """
    ctx = create_underwriting_application()
    aid = ctx["application"]["id"]
    add_collateral(aid, asset_type="REAL_ESTATE", appraised_value_cents=70_000_000)
    fp = validate_success(api.create_form_package(
        {"application_id": aid, "form_1919_complete": True, "form_1920_complete": True,
         "character_cleared": False}, OFFICER), 201)
    validate_success(api.submit_form_package(fp["id"], OFFICER), 200)
    validate_success(api.review_form_package(fp["id"], APPROVER), 200)  # -> FLAGGED
    memo = author_credit_memo(aid, recommendation="APPROVE")
    validate_error(api.submit_credit_memo(memo["id"], OFFICER),
                   ApiErrorId.ERR_FORM_PACKAGE_NOT_CLEARED.value)
    memos = validate_success(api.list_credit_memos(aid, SBA), 200)
    by_id = {m["id"]: m for m in memos}
    assert by_id[memo["id"]]["status"] == "DRAFT"


# ─── cross_entity_state_dependency: sale settle requires Application AUTHORIZED+ ─

def test_guaranty_sale_settle_blocked_while_application_only_approved(api):
    """PRD §3.8: "the application's origination `status` must be `AUTHORIZED`, `DISBURSING`, or `CLOSED`, or the settle is rejected with `ERR_GUARANTY_NOT_SELLABLE`."

    Design: Difficulty/cross_entity_state_dependency/guaranty_sale_settle_requires_application_authorized
    """
    # APPROVED (not yet AUTHORIZED) loan: guaranteed_amount_cents is 0, so a sale created with
    # sold_principal_cents 0 passes the mismatch check; settling while status==APPROVED hits the
    # cross-entity gate.
    ctx = reach_approved()
    aid = ctx["application"]["id"]
    app_v = ctx["application"]["version"]
    sale = offer_guaranty_sale(aid, 0, premium_bps=100)
    res = api.settle_guaranty_sale(sale["id"], {"expected_application_version": app_v}, INVESTOR)
    validate_error(res, ApiErrorId.ERR_GUARANTY_NOT_SELLABLE.value)


def test_guaranty_sale_remains_offered_when_application_not_sellable(api):
    """PRD §3.8: "the application's origination `status` must be `AUTHORIZED`, `DISBURSING`, or `CLOSED`, or the settle is rejected with `ERR_GUARANTY_NOT_SELLABLE`."
    PRD §3.8: "On a successful settle the system moves the sale to `SETTLED`, advances the application's `guaranty_status` from `RETAINED` to `SOLD`".

    Design: Difficulty/cross_entity_state_dependency/guaranty_sale_settle_requires_application_authorized
    """
    ctx = reach_approved()
    aid = ctx["application"]["id"]
    app_v = ctx["application"]["version"]
    sale = offer_guaranty_sale(aid, 0, premium_bps=100)
    validate_error(
        api.settle_guaranty_sale(sale["id"], {"expected_application_version": app_v}, INVESTOR),
        ApiErrorId.ERR_GUARANTY_NOT_SELLABLE.value)
    sales = validate_success(api.list_application_guaranty_sales(aid, SBA), 200)
    by_id = {s["id"]: s for s in sales}
    assert by_id[sale["id"]]["status"] == "OFFERED"
    app_after = validate_success(api.get_application(aid, SBA), 200)
    assert app_after["guaranty_status"] == "RETAINED"
