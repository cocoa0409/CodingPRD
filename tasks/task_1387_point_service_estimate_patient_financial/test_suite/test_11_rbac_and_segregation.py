"""Role authorization and segregation-of-duties enforcement."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_case,
    create_patient,
    make_reviewer_headers,
    make_supervisor_headers,
    pledge_and_post_deposit,
    request_authorization,
    set_clock,
    setup_insured_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

COUNSELOR = TEST_USERS["counselor_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestRoleExclusiveOperations:
    def test_price_estimate_as_registrar_returns_403(self, api):
        """PRD §2.1: "Each operation is restricted to a named set of roles (see
        §4); a caller whose role is valid but not listed for the endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /clearance/estimates/{id}/price — "FinancialCounselor".

        Design: Corner/rbac/price_estimate_as_registrar_returns_403
        """
        ctx = setup_insured_scenario(mrn="MRN-RB-1", bundling_rule="NONE",
                                     reduction_pct=None)
        res = api.price_estimate(ctx["estimate"]["id"], REGISTRAR)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        est = validate_success(api.get_estimate(ctx["estimate"]["id"], COUNSELOR), 200)
        assert est["status"] == "DRAFT"

    def test_decide_authorization_as_counselor_returns_403(self, api):
        """PRD §2.1: "Each operation is restricted to a named set of roles (see
        §4); a caller whose role is valid but not listed for the endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /clearance/authorizations/{id}/decide —
        "UtilizationReviewer".

        Design: Corner/rbac/decide_authorization_as_counselor_returns_403
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-RB-2")
        case = create_case(patient["id"])
        auth = request_authorization(case["id"], cpt_codes=("27447",),
                                     requester_id="ur-1")
        res = api.decide_authorization(
            auth["id"],
            {"decision": "APPROVED", "medical_necessity_met": True,
             "valid_from": "2026-08-10", "valid_to": "2026-08-31"},
            COUNSELOR)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        auths, _m = validate_paginated(
            api.list_case_authorizations(case["id"], SUPERVISOR))
        assert auths[0]["status"] == "REQUESTED"

    def test_refund_deposit_as_counselor_returns_403(self, api):
        """PRD §2.1: "Each operation is restricted to a named set of roles (see
        §4); a caller whose role is valid but not listed for the endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /clearance/deposits/{id}/refund — "ClearanceSupervisor".

        Design: Corner/rbac/refund_deposit_as_counselor_returns_403
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-RB-3")
        case = create_case(patient["id"])
        deposit = pledge_and_post_deposit(case["id"], 100000)
        assert deposit["status"] == "POSTED"
        res = api.refund_deposit(deposit["id"], COUNSELOR)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        deposits, _m = validate_paginated(
            api.list_case_deposits(case["id"], SUPERVISOR))
        assert deposits[0]["status"] == "POSTED"


class TestSegregationOfDuties:
    def test_segregation_auth_decide_by_requester_returns_403(self, api):
        """PRD §2.9: "An authorization decision is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the deciding reviewer's
        `X-User-ID` equals the requesting reviewer's recorded
        `requested_by_user_id`."

        Design: Corner/rbac/segregation_auth_decide_by_requester_returns_403
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-RB-4")
        case = create_case(patient["id"])
        auth = request_authorization(case["id"], cpt_codes=("27447",),
                                     requester_id="ur-1")
        payload = {"decision": "APPROVED", "medical_necessity_met": True,
                   "valid_from": "2026-08-10", "valid_to": "2026-08-31"}
        res = api.decide_authorization(auth["id"], payload,
                                       make_reviewer_headers("ur-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        auths, _m = validate_paginated(
            api.list_case_authorizations(case["id"], SUPERVISOR))
        assert auths[0]["status"] == "REQUESTED"
        # A different reviewer may decide.
        decided = validate_success(api.decide_authorization(
            auth["id"], payload, make_reviewer_headers("ur-2")), 200)
        assert decided["status"] == "APPROVED"

    def test_segregation_escalation_approve_by_opener_returns_403(self, api):
        """PRD §2.9: "The same rule binds escalation closure: approving or
        rejecting an escalation is rejected with `ERR_SEGREGATION_OF_DUTIES`
        when the decider's `X-User-ID` equals the escalation's
        `opened_by_user_id`."
        PRD §2.9: "There is exactly one exemption: escalations opened
        automatically by the system carry the literal string `"system"` as
        their `opened_by_user_id`, and any supervisor may decide them."

        Design: Corner/rbac/segregation_escalation_approve_by_opener_returns_403
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-RB-5")
        case = create_case(patient["id"])
        escalation = validate_success(api.create_escalation(
            case["id"], {"reason": "AUTH_EXCEPTION",
                         "note": "payer demands peer review"},
            make_supervisor_headers("sup-1")), 201)
        assert escalation["opened_by_user_id"] == "sup-1"
        res = api.approve_escalation(escalation["id"], {},
                                     make_supervisor_headers("sup-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        escalations, _m = validate_paginated(
            api.list_case_escalations(case["id"], SUPERVISOR))
        assert escalations[0]["status"] == "OPEN"
        # Another supervisor may decide.
        approved = validate_success(api.approve_escalation(
            escalation["id"], {"decision_note": "ok"},
            make_supervisor_headers("sup-2")), 200)
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "sup-2"
