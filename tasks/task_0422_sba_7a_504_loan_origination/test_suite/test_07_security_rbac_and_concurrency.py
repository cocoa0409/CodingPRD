"""RBAC, header validation, business-rule error paths, and optimistic concurrency on
guaranty-sale settle.

Covers corner-design sections: rbac, errors, validations (active), and
cross_cutting_complexity_layers (active OCC instance).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_lender_payload,
    create_draft_application,
    reach_authorized, reach_pending_approval, reach_fully_disbursed, reach_defaulted,
    create_and_post_disbursement,
    offer_guaranty_sale,
    build_user_headers,
    TEST_USERS,
)
from test_helpers.api_client import api_client

OFFICER = TEST_USERS["loan_officer_headers"]
APPROVER = TEST_USERS["credit_approver_headers"]
SBA = TEST_USERS["sba_officer_headers"]
INVESTOR = TEST_USERS["investor_servicer_headers"]


# ─── rbac: missing user-context headers ───────────────────────────────────────

def test_missing_user_headers_returns_header_error(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_headers_returns_header_error
    """
    res = api.create_lender(create_lender_payload(name="NoHdr CDC", program="7A"), headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_loan_officer_cannot_authorize(api):
    """PRD §2.1: "When a caller presents a valid role that is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §4 endpoint table: POST /sba/applications/{applicationId}/authorize — Authorized
    Role(s): SbaOfficer.

    Design: Corner/rbac/loan_officer_cannot_authorize
    """
    ctx = reach_pending_approval(recommendation="APPROVE")
    aid = ctx["application"]["id"]
    validate_success(api.approve_application(aid, APPROVER), 200)  # now APPROVED
    res = api.authorize_application(aid, OFFICER)  # LoanOfficer attempting an SbaOfficer op
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["status"] == "APPROVED"


def test_investor_cannot_open_liquidation(api):
    """PRD §2.1: "When a caller presents a valid role that is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §4 endpoint table: POST /sba/liquidations — Authorized Role(s): LoanOfficer.

    Design: Corner/rbac/investor_cannot_open_liquidation
    """
    ctx = reach_defaulted()
    aid = ctx["application"]["id"]
    res = api.create_liquidation(
        {"application_id": aid, "recovery_cents": 1_000_000, "expense_cents": 0}, INVESTOR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ─── validations (active): segregation of duties ──────────────────────────────

def test_approve_by_memo_author_returns_segregation_of_duties(api):
    """PRD §3.5: "the acting approver's `X-User-ID` must differ from the submitted memo's `authored_by_user_id`, or the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/validations/segregation_of_duties_excluded
    """
    # Memo authored by officer-1; approval attempted by the SAME id officer-1 acting as
    # CreditApprover.
    ctx = reach_pending_approval(recommendation="APPROVE")
    aid = ctx["application"]["id"]
    author_as_approver = build_user_headers("officer-1", "CreditApprover")
    res = api.approve_application(aid, author_as_approver)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["status"] == "PENDING_APPROVAL"


# ─── errors (active): business-rule failure paths ─────────────────────────────

def test_sale_principal_mismatch_on_create(api):
    """PRD §3.8: "the `sold_principal_cents` must equal the application's `guaranteed_amount_cents`, or the offer is rejected with `ERR_SALE_PRINCIPAL_MISMATCH`."

    Design: Corner/errors/sale_principal_mismatch_on_create
    """
    # AUTHORIZED loan gp 0.75 -> guaranteed_amount_cents 37500000; offer 30000000 -> mismatch.
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    res = api.create_guaranty_sale(
        {"application_id": aid, "investor_user_id": "inv-9", "sold_principal_cents": 30_000_000,
         "premium_bps": 350}, OFFICER)
    validate_error(res, ApiErrorId.ERR_SALE_PRINCIPAL_MISMATCH.value)


def test_submit_ineligible_business_returns_error(api):
    """PRD §3.4: "the borrower's `is_eligible_business_type` must be true, or the submit is rejected with `ERR_INELIGIBLE_BUSINESS`."

    Design: Corner/errors/ineligible_business_excluded
    """
    ctx = create_draft_application(
        borrower_overrides={"naics_code": "525910", "is_eligible_business_type": False})
    aid = ctx["application"]["id"]
    res = api.submit_application(aid, OFFICER)
    validate_error(res, ApiErrorId.ERR_INELIGIBLE_BUSINESS.value)
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["status"] == "DRAFT"


def test_close_not_fully_disbursed_returns_error(api):
    """PRD §3.7: "Closing requires that `disbursed_amount_cents` equal `requested_amount_cents`, or it is rejected with `ERR_NOT_FULLY_DISBURSED`."

    Design: Corner/errors/not_fully_disbursed_on_close
    """
    # DISBURSING loan: requested 50000000, one POSTED draw of 10000000 -> close rejected.
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    create_and_post_disbursement(aid, 10_000_000, 0, 30, label="Draw 1")
    res = api.close_application(aid, OFFICER)
    validate_error(res, ApiErrorId.ERR_NOT_FULLY_DISBURSED.value)
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["status"] == "DISBURSING"


# ─── cross_cutting (active): OCC stale application version on sale settle ──────

def test_occ_stale_application_version_on_second_sale_settle(api):
    """PRD §2.9: "If that value does not match the application's current `version` — because another writer has already settled a sale and advanced the loan's version since the client last read it — the settle is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412), preventing the client from overwriting a settlement it never observed."
    PRD §2.9: "When the versions agree, the settle proceeds and increments the application's `version` by one as part of its side effects."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_application_version_on_sale_settle
    """
    # Two OFFERED sales on one AUTHORIZED loan; settling saleA bumps Application.version.
    # Settling saleB with the pre-A expected_application_version is stale.
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    av = ctx["application"]["version"]
    guaranteed = ctx["application"]["guaranteed_amount_cents"]
    sale_a = offer_guaranty_sale(aid, guaranteed, premium_bps=200, investor_user_id="inv-9")
    sale_b = offer_guaranty_sale(aid, guaranteed, premium_bps=250, investor_user_id="inv-8")

    validate_success(
        api.settle_guaranty_sale(sale_a["id"], {"expected_application_version": av}, INVESTOR), 200)
    res = api.settle_guaranty_sale(sale_b["id"], {"expected_application_version": av}, INVESTOR)
    validate_error(res, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value)
    sales = validate_success(api.list_application_guaranty_sales(aid, SBA), 200)
    by_id = {s["id"]: s for s in sales}
    assert by_id[sale_b["id"]]["status"] == "OFFERED"
