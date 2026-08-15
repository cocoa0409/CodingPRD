"""Context-header validation, role permission denials, and borrower ownership
(PRD sections 2.1, 2.7, 3.2, 3.6).
"""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, api_client, create_borrower,
    create_draft_loan, create_draw_payload, disburse_draw, get_success_data,
    make_borrower_headers, setup_active_loan, validate_error,
    validate_paginated, validate_success,
)

OFFICER = TEST_USERS["loan_officer_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]

CAPPED_50M = {
    "collateral_type": "REAL_ESTATE",
    "appraised_value_cents": 60_000_000,
    "projected_revenue_cents": 80_000_000,
    "projected_expenses_cents": 50_000_000,
}


def test_missing_auth_header_returns_400(api):
    """PRD section 2.1: "A request missing either header, or carrying a role
    string outside that declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)." PRD section 2.7:
    "When a single request would violate several rules, the server reports only
    one failure: the violation whose category sits earliest in the precedence
    below." (context headers are tier 1; existence is tier 5.)

    Design: Corner/validations/missing_auth_header_returns_400
    """
    resp = api.get_association(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_borrower_cannot_approve_draw_forbidden(api):
    """PRD section 2.1: "A caller whose role is not listed for the target endpoint
    is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD section 3.6:
    "Approval belongs to the officer and enforces four gates in a fixed order: the
    loan must be `ACTIVE`, else `ERR_LOAN_NOT_ACTIVE`; the posture must not be
    `DELINQUENT` or `DEFAULT`, else `ERR_LOAN_POSTURE_BLOCKS_DRAWS`; at least one
    policy `ASSIGNED` and `ACTIVE` for this loan must exist, else
    `ERR_INSURANCE_NOT_ASSIGNED`; and the amount must fit available credit, else
    `ERR_DRAW_EXCEEDS_AVAILABILITY`."

    Design: Corner/rbac/borrower_cannot_approve_draw_forbidden
    """
    ctx = setup_active_loan(**CAPPED_50M)
    borrower = make_borrower_headers(ctx["bor"]["id"])
    drw = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=ctx["loan"]["id"], amount_cents=100_000,
                            purpose="FUEL"), borrower))
    resp = api.approve_draw_request(drw["id"], borrower)  # the owning borrower, even
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert get_success_data(api.get_draw_request(drw["id"], OFFICER))["status"] == "REQUESTED"


def test_loan_officer_cannot_approve_loan_forbidden(api):
    """PRD section 2.1: "A caller whose role is not listed for the target endpoint
    is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD section 3.2:
    "Submission by the officer moves the application `DRAFT` → `SUBMITTED`.
    Committee approval then sets the commitment: the supplied
    `approved_commitment_cents` must be a positive amount no greater than the
    `requested_commitment_cents`, and anything outside that range is rejected as
    `ERR_INVALID_REQUEST`."

    Design: Corner/rbac/loan_officer_cannot_approve_loan_forbidden
    """
    ctx = create_draft_loan()
    get_success_data(api.submit_loan(ctx["loan"]["id"], OFFICER))
    resp = api.approve_loan(ctx["loan"]["id"],
                            {"approved_commitment_cents": 50_000_000}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert get_success_data(api.get_loan(ctx["loan"]["id"], OFFICER))["status"] == "SUBMITTED"


def test_adjuster_cannot_disburse_draw_forbidden(api):
    """PRD section 2.1: "A caller whose role is not listed for the target endpoint
    is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." PRD section 3.6: "The
    officer disburses an `APPROVED` draw; interest first accrues to the clock date,
    then `outstanding_principal_cents` grows by the `amount_cents`,
    `pending_draw_cents` shrinks by the same amount, the `disbursement_date` is
    stamped with the clock, and the draw lands in `DISBURSED` with the standard
    cascade behind it."

    Design: Corner/rbac/adjuster_cannot_disburse_draw_forbidden
    """
    ctx = setup_active_loan(**CAPPED_50M)
    drw = get_success_data(api.create_draw_request(
        create_draw_payload(loan_account_id=ctx["loan"]["id"], amount_cents=100_000,
                            purpose="FUEL"), OFFICER))
    get_success_data(api.approve_draw_request(drw["id"], OFFICER))
    resp = api.disburse_draw_request(drw["id"], ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert get_success_data(api.get_draw_request(drw["id"], OFFICER))["status"] == "APPROVED"


def test_borrower_on_other_borrowers_loan_returns_403(api):
    """PRD section 2.1: "When `X-User-Role` is `Borrower`, `X-User-ID` is the `id`
    of the acting `Borrower` record; ownership checks on any resource that traces
    back to a borrower — creating a draw, repayment, crop budget, deferral request,
    or insurance claim against one of its loans, cancelling one of its own draws,
    or cancelling one of its own policies — compare the resource's owning borrower
    to `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP
    403)."

    Design: Corner/rbac/borrower_on_other_borrowers_loan_returns_403
    """
    ctx = setup_active_loan(**CAPPED_50M)  # owned by borrower A
    bor_b = create_borrower(ctx["assoc"]["id"], legal_name="Neighbor Farms",
                            tax_id="41-0000002")
    resp = api.create_draw_request(
        create_draw_payload(loan_account_id=ctx["loan"]["id"], amount_cents=100_000,
                            purpose="FUEL"),
        make_borrower_headers(bor_b["id"]))  # borrower B acts on A's loan
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_OWNED)
    _data, meta = validate_paginated(
        api.list_draw_requests(OFFICER, {"loan_account_id": ctx["loan"]["id"]}))
    assert meta["total_count"] == 0, "the rejected request created no draw"
