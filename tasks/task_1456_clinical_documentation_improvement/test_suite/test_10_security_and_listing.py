"""Authentication, role authorization, error envelope, and list filtering."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock,
    assert_denial_risk_target,
    create_case,
    create_cdi_review_payload,
    create_denial_risk_target_payload,
    create_escalation_policy_payload,
    create_program,
    create_provider,
    finalize_case,
    get_case,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:
    def test_unauthenticated_request_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside
        this enumeration, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_request_returns_401
        """
        program = create_program()
        resp = api.get_cdi_program(program["id"], headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_missing_role_header_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside
        this enumeration, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_request_returns_401
        """
        program = create_program()
        resp = api.get_cdi_program(
            program["id"], headers={"X-User-ID": "someone", "Content-Type": "application/json"}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_provider_cannot_create_cdi_program(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED`."
        PRD §4: "POST | `/api/cdi-programs` | Create a CDI program | CDIManager"

        Design: Corner/validations/provider_cannot_create_cdi_program
        """
        from test_helpers import make_provider_headers
        program = create_program()
        provider = create_provider(program["id"])
        resp = api.create_cdi_program(
            {"facility_name": "X", "program_code": "X1", "baseline_cmi": 1.0},
            make_provider_headers(provider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_himcoder_cannot_create_review(self, api, him_coder_headers):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED`."
        PRD §4: "POST | `/api/cdi-reviews` | Open a CDI review on a case |
        CDISpecialist"

        Design: Corner/rbac/himcoder_cannot_create_review
        """
        program = create_program()
        provider = create_provider(program["id"])
        case = create_case(program["id"], provider["id"])
        resp = api.create_cdi_review(
            create_cdi_review_payload(case["id"]), him_coder_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_cdispecialist_cannot_finalize_coding(self, api, cdi_specialist_headers):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED`."
        PRD §4: "POST | `/api/patient-cases/{caseId}/finalize-coding` | Attempt
        final coding (OCC via `expected_case_version`) | HIMCoder"

        Design: Corner/rbac/cdispecialist_cannot_finalize_coding
        """
        program = create_program()
        provider = create_provider(program["id"])
        case = create_case(program["id"], provider["id"], discharge_period=1)
        advance_clock(program["id"], 2)
        current = get_case(case["id"])
        resp = api.finalize_coding(
            case["id"],
            {
                "coder_drg_code": "A",
                "coder_drg_weight": 1.0,
                "expected_case_version": current["version"],
            },
            cdi_specialist_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_compliance_auditor_can_create_denial_target_but_not_policy(
        self, api, compliance_auditor_headers
    ):
        """PRD §4: "POST | `/api/denial-risk-targets` | Create a denial risk
        target | CDIManager, ComplianceAuditor"
        PRD §4: "POST | `/api/escalation-policies` | Create an escalation policy |
        CDIManager"
        PRD §2.1: "A request whose role is valid but not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/compliance_auditor_can_create_denial_target_but_not_policy
        """
        program = create_program()
        target = validate_success(
            api.create_denial_risk_target(
                create_denial_risk_target_payload(
                    program["id"], severity_floor=2, active_from_period=0,
                    active_to_period=10,
                ),
                compliance_auditor_headers,
            ),
            expected_status=201,
        )
        assert_denial_risk_target(target)
        resp = api.create_escalation_policy(
            create_escalation_policy_payload(program["id"]), compliance_auditor_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api, cdi_manager_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "response_type": "error" and a `data`
        object carrying "error_id" and "message"; "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape
        """
        create_program()
        resp = api.get_patient_case(NON_EXISTENT_UUID, cdi_manager_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert "meta" in body
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0


class TestCaseListing:
    def test_list_patient_cases_filter_by_status(self, api, cdi_specialist_headers):
        """PRD §4: "GET | `/api/patient-cases` | List cases (filterable by
        `cdi_program_id`, `status`, `attending_provider_id`, `priority_score_min`)"
        PRD §2.3: "the `meta` object of every list response carries the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_patient_cases_filter_by_status
        """
        program = create_program()
        provider = create_provider(program["id"])
        create_case(program["id"], provider["id"], mrn="M1", discharge_period=1)
        create_case(program["id"], provider["id"], mrn="M2", discharge_period=1)
        c3 = create_case(program["id"], provider["id"], mrn="M3", discharge_period=1)
        advance_clock(program["id"], 2)
        finalize_case(c3["id"])
        data, meta = validate_paginated(
            api.list_patient_cases(cdi_specialist_headers, params={"status": "OPEN"})
        )
        assert len(data) >= 1
        assert all(c["status"] == "OPEN" for c in data)
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta
