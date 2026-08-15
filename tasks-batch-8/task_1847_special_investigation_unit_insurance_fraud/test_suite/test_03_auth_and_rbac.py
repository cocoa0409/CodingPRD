"""Authentication, authorization, and role-based access denials."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_manager_headers, make_compliance_headers,
    create_adjuster, create_claim, create_referral, triage_referral,
    accept_referral, open_case, assign_investigator, create_investigator,
    log_evidence, submit_evidence_review, admit_evidence,
    setup_case_decision_pending,
)
from test_helpers.api_client import api_client
from prd_bench_local_runner.testing import build_user_headers


class TestUnauthenticated:
    def test_missing_role_header_returns_401(self, api):
        """PRD §2.1: "A request with a missing or malformed header is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        # Call with no auth headers at all
        resp = api_client._request("GET", "/siu/claims", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestUnauthorized:
    def test_adjuster_cannot_triage_referral(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST | `/siu/referrals/{referralId}/triage` | Triage referral |
        SIUManager"

        Design: Corner/validations/unauthorized_role_for_endpoint
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj)
        ref = create_referral(claim, headers=ah)
        resp = api_client.triage_referral(ref["id"], {}, ah)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestRBACDenials:
    def test_adjuster_cannot_admit_evidence(self, api):
        """PRD §4: "POST | `/siu/cases/{caseId}/evidence/{evidenceId}/admit` |
        Admit evidence (OCC on case) | SIUManager"
        PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/endpoints/adjuster_cannot_admit_evidence
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv, ih = create_investigator(manager_headers=mh)
        claim = create_claim(adj)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg, case = assign_investigator(case, inv, manager_headers=mh)
        ev = log_evidence(case, inv)
        ev = submit_evidence_review(case, ev, inv)
        # Adjuster attempts manager-only admit
        resp = api_client.admit_evidence(
            case["id"], ev["id"],
            {"expected_case_version": case["version"]}, ah)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_investigator_cannot_close_case(self, api):
        """PRD §4: "POST | `/siu/cases/{caseId}/close` | Close case | SIUManager"
        PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/endpoints/investigator_cannot_close_case
        """
        ctx = setup_case_decision_pending()
        resp = api_client.close_case(
            ctx["case"]["id"], {"closed_reason": "UNSUBSTANTIATED"},
            ctx["investigator_headers"])
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_compliance_officer_cannot_create_claim(self, api):
        """PRD §4: "POST | `/siu/claims` | Register a new claim | Adjuster"
        PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/endpoints/compliance_officer_cannot_create_claims
        """
        mh = make_manager_headers()
        adj, _ = create_adjuster(manager_headers=mh)
        ch = make_compliance_headers()
        resp = api_client.create_claim(
            {"policy_number": "P", "state_code": "CA", "adjuster_id": adj["id"],
             "claimed_amount_cents": 100}, ch)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
