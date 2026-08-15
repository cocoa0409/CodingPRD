"""Role-based access control, auth-header checks, and validation precedence."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    api_client,
    create_broker,
    create_case,
    create_case_payload,
    create_broker_payload,
    create_case_in_claims_pending,
    create_case_in_rating,
    create_case_in_census_pending,
    create_census_payload,
    add_claims_record,
    submit_claims_record,
    add_modeled_plan,
    create_quote_payload,
    make_broker_headers,
    make_underwriter_headers,
    build_user_headers,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
SU = TEST_USERS["senior_underwriter_headers"]
CO = TEST_USERS["compliance_headers"]


class TestAuthHeaders:
    def test_missing_user_context_header(self):
        """PRD section 2.1: "A request missing either header, or carrying a value
        the server cannot interpret, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_context_header
        """
        headers = {"X-User-ID": "", "X-User-Role": "Underwriter",
                   "Content-Type": "application/json"}
        resp = api_client.create_broker(create_broker_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleDenials:
    def test_broker_cannot_create_case(self):
        """PRD section 2.1: "an authenticated caller whose role is not authorized
        for the requested operation is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."
        PRD section 4: POST /underwriting-cases is authorized for Underwriter
        only.

        Design: Corner/rbac/broker_cannot_create_case
        """
        broker = create_broker()
        resp = api_client.create_case(
            create_case_payload(broker["id"]),
            make_broker_headers(broker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        _cases, meta = validate_paginated(api_client.list_cases(UW))
        assert meta["total_count"] == 0

    def test_underwriter_cannot_review_claims(self):
        """PRD section 3.3: "Review is reserved for a `SeniorUnderwriter`".
        PRD section 2.1: "an authenticated caller whose role is not authorized
        for the requested operation is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/underwriter_cannot_review_claims
        """
        broker = create_broker()
        case, _ = create_case_in_claims_pending(broker["id"])
        claims = add_claims_record(case["id"])
        submit_claims_record(claims["id"])
        resp = api_client.review_claims(
            claims["id"], make_underwriter_headers("uw-001")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        claims = get_success_data(api_client.get_claims_experience(claims["id"], UW))
        assert claims["status"] == "SUBMITTED"

    def test_compliance_officer_read_only(self):
        """PRD section 2.1: "When `X-User-Role` is `ComplianceOfficer`, `X-User-ID`
        is an opaque identifier with read-only reach: the role can view every
        entity in the system but can perform no mutations."

        Design: Corner/rbac/compliance_officer_read_only
        """
        broker = create_broker()
        case = create_case(broker["id"])
        got = validate_success(api_client.get_case(case["id"], CO))
        assert got["id"] == case["id"]
        resp = api_client.create_case(
            create_case_payload(broker["id"], group_name="ForbiddenCo"), CO
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_senior_underwriter_cannot_create_quote(self):
        """PRD section 4: POST /underwriting-cases/{caseId}/quotes is authorized
        for Underwriter only.
        PRD section 2.1: "an authenticated caller whose role is not authorized
        for the requested operation is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/senior_underwriter_cannot_create_quote
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        plan = add_modeled_plan(case["id"])
        case_now = get_success_data(api_client.get_case(case["id"], UW))
        resp = api_client.create_quote(
            case["id"],
            create_quote_payload(plan["id"], case_now["version"]),
            SU,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        _quotes, meta = validate_paginated(api_client.list_quotes(case["id"], UW))
        assert meta["total_count"] == 0


class TestValidationPrecedence:
    def test_auth_beats_state_on_request_claims(self):
        """PRD section 2.6: "Header presence and well-formedness are checked
        first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), followed by role
        authorization for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`), followed by
        existence of every resource identifier in the path (`ERR_NOT_FOUND`)."
        PRD section 2.6: "After existence and version checks, business-state
        guards fire: the parent-case state guard (`ERR_CASE_INVALID_STATE` and
        its more specific case-state errors), then the entity's own transition
        guard (`ERR_INVALID_STATE_TRANSITION` and the more specific per-entity
        "not in state X" errors), then the rule-specific business constraints
        enumerated throughout §3".
        PRD section 4: POST /underwriting-cases/{caseId}/request-claims is
        authorized for Underwriter only.

        Design: Difficulty/priority_pair_validation_conflict/auth_beats_state_on_request_claims
        """
        broker = create_broker()
        case = create_case(broker["id"])  # stays INTAKE
        # Broker role is denied outright even though the state check would also
        # fail (case not CENSUS_RECEIVED).
        resp = api_client.request_claims(
            case["id"], make_broker_headers(broker["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "INTAKE"

    def test_auth_beats_state_on_request_claims_from_census_pending(self):
        """PRD section 2.6: "Header presence and well-formedness are checked
        first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), followed by role
        authorization for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`), followed by
        existence of every resource identifier in the path (`ERR_NOT_FOUND`)."
        A Broker calling request-claims is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` regardless of the case's state, since POST
        /underwriting-cases/{caseId}/request-claims is authorized for
        Underwriter only (PRD section 4).

        Design: Difficulty/priority_pair_validation_conflict/auth_beats_state_on_request_claims
        """
        broker = create_broker()
        case = create_case_in_census_pending(broker["id"])
        resp = api_client.request_claims(
            case["id"], make_broker_headers(broker["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestCaseStateGuards:
    def test_submit_for_census_twice_fails(self):
        """PRD section 3.1: "the case must still be in `INTAKE` (otherwise
        `ERR_CASE_NOT_IN_INTAKE`)".

        Design: Corner/validations/submit_for_census_twice_fails
        """
        broker = create_broker()
        case = create_case_in_census_pending(broker["id"])
        resp = api_client.submit_for_census(case["id"], UW)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_INTAKE)
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "CENSUS_PENDING"

    def test_request_claims_from_census_pending_fails(self):
        """PRD section 3.3: "requesting claims data requires the case to be in
        `CENSUS_RECEIVED` (else `ERR_CASE_NOT_IN_CENSUS_RECEIVED`)".

        Design: Corner/validations/request_claims_from_census_pending_fails
        """
        broker = create_broker()
        case = create_case_in_census_pending(broker["id"])
        census = get_success_data(
            api_client.create_census_snapshot(
                case["id"], create_census_payload(), UW
            )
        )
        # Census submitted but not yet validated -> case still CENSUS_PENDING.
        resp = api_client.request_claims(case["id"], UW)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_CENSUS_RECEIVED)
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "CENSUS_PENDING"
