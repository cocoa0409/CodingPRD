"""Authentication, authorization, and role partitioning across the five
roles' exclusive operations."""
from test_helpers import (
    ApiErrorId,
    add_measure,
    build_approved_application,
    build_submitted_application,
    create_active_ally,
    create_evaluation_adjustment_payload,
    create_open_program,
    create_program_year,
    create_program_year_payload,
    make_inspector_headers,
    make_processor_headers,
    make_regulator_headers,
    make_trade_ally_headers,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in
        which they act. The system recognizes exactly five roles:
        `ProgramAdministrator`, `TradeAlly`, `VerificationInspector`,
        `PaymentProcessor`, and `RegulatorAnalyst`. A request with missing or
        malformed headers is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a
        well-authenticated request whose role is not authorized for the target
        operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        res = api.list_program_years(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_wrong_role_for_endpoint_returns_unauthorized(self, api):
        """PRD §2.1: "a well-authenticated request whose role is not authorized
        for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/program-years` | Create a new program year |
        ProgramAdministrator |"

        Design: Corner/validations/wrong_role_for_endpoint_returns_unauthorized
        """
        ally = create_active_ally()
        res = api.create_program_year(
            create_program_year_payload(
                program_code="P1", budget_cap_cents=1_000, savings_goal_kwh=100
            ),
            make_trade_ally_headers(ally["id"]),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestExclusiveOperations:
    def test_verification_inspector_cannot_open_program_year(self, api):
        """PRD §2.1: "a well-authenticated request whose role is not authorized
        for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/program-years/{id}/open` | Open a DRAFT program year
        | ProgramAdministrator |"

        Design: Corner/rbac/verification_inspector_cannot_open_program_year
        """
        py = create_program_year()
        add_measure(py["id"])
        res = api.open_program_year(py["id"], make_inspector_headers())
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_payment_processor_cannot_verify_application(self, api):
        """PRD §2.1: "a well-authenticated request whose role is not authorized
        for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/applications/{id}/verify` | Verify an application;
        finalize savings | VerificationInspector |"

        Design: Corner/rbac/payment_processor_cannot_verify_application
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app, _line = build_submitted_application(py, ally, measures[0])

        res = api.verify_application(app["id"], make_processor_headers())
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_regulator_analyst_cannot_pay_application(self, api):
        """PRD §2.1: "a well-authenticated request whose role is not authorized
        for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/applications/{id}/pay` | Pay an APPROVED application
        | PaymentProcessor |"

        Design: Corner/rbac/regulator_analyst_cannot_pay_application
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app, _line = build_approved_application(py, ally, measures[0], claim="DEEMED")

        res = api.pay_application(app["id"], make_regulator_headers())
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_trade_ally_cannot_create_evaluation_adjustment(self, api, admin_headers):
        """PRD §2.1: "a well-authenticated request whose role is not authorized
        for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/evaluation-adjustments` | Record an evaluation
        adjustment | RegulatorAnalyst |"

        Design: Corner/rbac/trade_ally_cannot_create_evaluation_adjustment
        """
        ally = create_active_ally()
        # Close the (empty-pipeline) program so the evaluation-adjustment
        # endpoint is in its normal operating state for the role check.
        py, _measures = create_open_program()
        py = validate_success(api.close_program_year(py["id"], admin_headers), 200)

        res = api.create_evaluation_adjustment(
            create_evaluation_adjustment_payload(
                py["id"], realization_rate_pct=90, effective_on="2026-08-13"
            ),
            make_trade_ally_headers(ally["id"]),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
