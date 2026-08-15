"""Authentication context, role authorization, and per-endpoint RBAC
denials (PRD §2.1, §2.6, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_carrier_payload,
    create_challenge_payload,
    create_violation_payload,
    make_accident,
    make_carrier,
    make_carrier_with_driver,
    make_coaching,
    make_drug_test,
    make_inspection_with_violation,
    make_audit_case,
    report_lab,
    validate_error,
)


class TestAuthenticationContext:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, naming their
        operational capacity. A request missing either header, carrying an empty
        value, or naming an unknown role is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.create_carrier(
            create_carrier_payload(dot_number="DOT-2301", legal_name="NoAuth"),
            headers={},
        )
        body = resp.json()
        assert body.get("response_type") == "error"
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)

    def test_forbidden_role_beats_not_found(self, api, analyst_headers):
        """PRD §2.6: "Every request is validated against the following stages,
        evaluated in the order given; a request that fails several checks
        receives the error from the earliest failing stage." — authorization
        (stage 2) precedes existence (stage 4), so a role that may not call the
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` even when the referenced
        resources do not exist.

        Design: Corner/validations/forbidden_role_beats_not_found
        """
        make_carrier(dot_number="DOT-2302")
        resp = api.create_violation(
            create_violation_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID, violation_code="X"),
            analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestRoleDenials:
    def test_mro_cannot_file_challenge_returns_403(self, api, mro_headers):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." and
        "`ComplianceAnalyst` is the data analyst: the inspection review
        workflow, DataQs filing and resubmission, and operation of the
        measurement cycle."

        Design: Corner/rbac/mro_cannot_file_challenge_returns_403
        """
        _, _, _, _, violation = make_inspection_with_violation(
            severity_weight=3,
            carrier_overrides={"dot_number": "DOT-2501"},
            inspection_overrides={"report_number": "R-2501", "state_code": "TN"},
        )
        resp = api.create_challenge(
            create_challenge_payload(violation["id"], evidence_note="mro attempt"),
            mro_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_insurance_analyst_cannot_close_audit_returns_403(
        self, api, insurance_headers
    ):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." and
        "`SafetyDirector` is the carrier safety executive: audit close, rating
        upgrade adjudication, and preventability determination."

        Design: Corner/rbac/insurance_analyst_cannot_close_audit_returns_403
        """
        carrier = make_carrier(dot_number="DOT-2502")
        case = make_audit_case(carrier["id"], field_work_duration_days=7)

        resp = api.close_audit_case(case["id"], insurance_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_safety_manager_cannot_verify_test_returns_403(self, api, manager_headers):
        """PRD §3.6: "Verification belongs exclusively to the
        `MedicalReviewOfficer`".
        PRD §2.1: "A request whose role is not listed among the endpoint's
        permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/safety_manager_cannot_verify_test_returns_403
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2503"}
        )
        test = make_drug_test(driver["id"], test_type="RANDOM", substance="DRUG")
        report_lab(test["id"], "NEGATIVE")

        resp = api.verify_test(test["id"], {"verdict": "VERIFIED_NEGATIVE"}, manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_compliance_analyst_cannot_escalate_coaching_returns_403(
        self, api, analyst_headers
    ):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." —
        coaching escalation is a `SafetyManager` operation (PRD §4).

        Design: Corner/rbac/compliance_analyst_cannot_escalate_coaching_returns_403
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2504"}
        )
        coaching = make_coaching(
            driver["id"], coaching_type="PROBATION", due_date="2026-12-01T00:00:00Z"
        )

        resp = api.escalate_coaching(coaching["id"], analyst_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_safety_admin_cannot_determine_preventability_returns_403(
        self, api, admin_headers
    ):
        """PRD §3.7: "Preventability is adjudicated by a `SafetyDirector`".
        PRD §2.1: "A request whose role is not listed among the endpoint's
        permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/safety_admin_cannot_determine_preventability_returns_403
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2505"}
        )
        accident = make_accident(carrier["id"], driver["id"])

        resp = api.determine_preventability(
            accident["id"], {"determination": "PREVENTABLE"}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_safety_director_cannot_run_cycle_returns_403(self, api, director_headers):
        """PRD §2.1: "`ComplianceAnalyst` is the data analyst: the inspection
        review workflow, DataQs filing and resubmission, and operation of the
        measurement cycle." and "A request whose role is not listed among the
        endpoint's permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
        403)."

        Design: Corner/rbac/safety_director_cannot_run_cycle_returns_403
        """
        carrier = make_carrier(dot_number="DOT-2506")
        resp = api.run_measurement_cycle({"carrier_id": carrier["id"]}, director_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
