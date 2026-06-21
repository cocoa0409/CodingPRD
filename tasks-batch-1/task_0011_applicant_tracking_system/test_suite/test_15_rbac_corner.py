"""Role-based access control: cross-role denial and unauthenticated requests."""
import pytest
from test_helpers import (
    api_client, validate_error, TEST_USERS,
    create_department, create_requisition, submit_requisition,
    setup_offer_in_state, accept_offer,
    fetch_background_check_for_offer, start_background_check,
    resolve_background_check_payload, set_clock,
    create_requisition_payload, make_headers, make_unauthenticated_headers,
)


# =========================================================================
# Instance: recruiter_cannot_approve_requisition
# =========================================================================

def test_recruiter_cannot_approve_requisition(api, recruiter_headers):
    """PRD §4: "POST /ats/requisitions/{id}/approve | Approve
    (`PENDING_APPROVAL` to `APPROVED`) | `HiringManager`"
    PRD §2.1: "If both headers are present but the named role is not
    authorised for the requested endpoint, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/recruiter_cannot_approve_requisition
    """
    dept = create_department()
    req = create_requisition(dept["id"], recruiter_headers=recruiter_headers)
    submit_requisition(req["id"], recruiter_headers=recruiter_headers)
    # Recruiter (not HiringManager) attempts approve.
    res = api_client.approve_requisition(req["id"], recruiter_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# =========================================================================
# Instance: candidate_cannot_create_requisition
# =========================================================================

def test_candidate_cannot_create_requisition(api, candidate_headers):
    """PRD §4: "POST /ats/requisitions | Create a requisition in `DRAFT` |
    `Recruiter`"
    PRD §2.1: "If both headers are present but the named role is not
    authorised for the requested endpoint, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/candidate_cannot_create_requisition
    """
    dept = create_department()
    payload = create_requisition_payload(dept["id"])
    res = api_client.create_requisition(payload, candidate_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# =========================================================================
# Instance: payroll_cannot_resolve_background_check
# =========================================================================

def test_payroll_cannot_resolve_background_check(api, payroll_officer_headers):
    """PRD §4: "POST /ats/background-checks/{id}/resolve | Resolve to `PASSED`
    or `FAILED` via `outcome` | `ComplianceOfficer`"
    PRD §2.1: "If both headers are present but the named role is not
    authorised for the requested endpoint, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/payroll_cannot_resolve_background_check
    """
    set_clock("2027-11-01T00:00:00Z")
    ctx = setup_offer_in_state(
        "EXTENDED",
        req_overrides={"base_salary_max_cents": 15_000_000},
        base_salary_cents=12_000_000,
    )
    cand = ctx["candidate"]
    offer = ctx["offer"]
    accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))
    bgc = fetch_background_check_for_offer(offer["id"])
    start_background_check(bgc["id"])
    res = api_client.resolve_background_check(
        bgc["id"], resolve_background_check_payload("PASSED"), payroll_officer_headers
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# =========================================================================
# Instance: unauthenticated_request_returns_401
# =========================================================================

def test_unauthenticated_request_returns_401(api):
    """PRD §2.1: "Every request to the API must carry two headers:
    `X-User-ID`, identifying the acting principal, and `X-User-Role`,
    naming that principal's role. If either header is missing or empty,
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "The sole exception to the authentication requirement is the
    test-driving clock endpoint, which does not enforce the authentication
    check."

    Design: Corner/rbac/unauthenticated_request_returns_401
    """
    # GET /ats/candidates with empty headers.
    res = api_client.list_candidates(make_unauthenticated_headers())
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
