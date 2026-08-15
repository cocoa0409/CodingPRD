"""Authentication headers, role-based access control, and schema validation."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_customer_account,
    build_user_headers,
    create_application_payload,
    create_draft_application,
    create_document_payload,
    create_program,
    drive_to_screen_passed,
    get_success_data,
    schedule_and_complete_exchange,
    schedule_and_pass_inspection,
    set_clock,
    setup_program_with_grid,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_administrator_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


class TestMissingContextHeader:
    def test_missing_or_unrecognized_headers_return_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role name
        that is not one of these six, is rejected with
        `ERR_MISSING_CONTEXT_HEADER` (HTTP 401)."

        Design: Corner/validations/v_missing_context_header_returns_unauthenticated
        """
        program = create_program("AUTH")
        # No auth headers at all.
        resp = api.get_program(program["id"], {})
        validate_error(resp, ApiErrorId.ERR_MISSING_CONTEXT_HEADER, 401)
        # A role name outside the six declared roles.
        resp = api.get_program(
            program["id"],
            {"X-User-ID": "someone", "X-User-Role": "SuperUser",
             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_CONTEXT_HEADER, 401)


class TestBodyForeignKey:
    def test_unresolvable_service_account_id_returns_422(self, api):
        """PRD §2.10: "Sixth, foreign keys in the request body — such as
        `service_account_id`, `program_id`, `transformer_id`, `feeder_id`,
        `customer_id`, `application_id`, and `supplemental_review_id` —
        resolving to existing resources (`ERR_INVALID_REFERENCE`)."

        Design: Corner/validations/v_body_fk_invalid_reference_returns_422
        """
        program = create_program("FK")
        customer = get_success_data(api.create_customer(
            {"full_name": "FK Cust", "email": "fk@example.com"}, ADMIN))
        applicant = build_user_headers(customer["id"], "Applicant")
        resp = api.create_application(
            create_application_payload(NON_EXISTENT_UUID, program["id"]),
            applicant)
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE, 422)


class TestApplicationSchemaValidation:
    def test_missing_required_field_returns_400(self, api):
        """PRD §2.10: "Fifth, request-schema soundness — required fields
        present, enum membership valid, quantities positive where required, an
        amend payload that is not empty, `period_end` strictly after
        `period_start` on readings, and a `deficiency_note` present whenever a
        completeness decision's `outcome` is `INCOMPLETE`
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/e_application_missing_required_field_returns_400
        """
        sc = setup_program_with_grid("RF", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        payload = create_application_payload(
            ctx["account"]["id"], sc["program"]["id"])
        del payload["system_size_watts_ac"]
        resp = api.create_application(payload, ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_unknown_technology_enum_returns_400(self, api):
        """PRD §3.3: "An applicant initiates the process by creating an
        application against an account they own, choosing a `technology` of
        `SOLAR_PV`, `WIND`, or `FUEL_CELL` and declaring the
        `system_size_watts_ac` and `estimated_annual_production_wh`, both
        strictly positive."
        PRD §2.10: "Fifth, request-schema soundness — required fields present,
        enum membership valid, quantities positive where required, an amend
        payload that is not empty, `period_end` strictly after `period_start`
        on readings, and a `deficiency_note` present whenever a completeness
        decision's `outcome` is `INCOMPLETE` (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/e_application_invalid_enum_returns_400
        """
        sc = setup_program_with_grid("EN", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        resp = api.create_application(
            create_application_payload(
                ctx["account"]["id"], sc["program"]["id"],
                technology="BIOMASS"),
            ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestNotFound:
    def test_get_unknown_application_returns_404(self, api):
        """PRD §2.10: "Fourth, the existence of every resource identifier in
        the path, validated left to right (`ERR_NOT_FOUND`)."

        Design: Corner/entities/e_get_application_not_found_returns_404
        """
        sc = setup_program_with_grid("NF", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        create_draft_application(sc, ctx, size=10_000, production=15_000_000)

        resp = api.get_application(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["data"]["message"].strip(), "error carries a message"


class TestRoleEnforcement:
    def test_engineer_cannot_grant_pto(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role per
        the endpoint table in §4; an authenticated user who attempts an
        operation outside their role is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §4: "| POST | `/applications/{application_id}/grant-pto` | Grant
        permission to operate | InterconnectionCoordinator |"

        Design: Corner/rbac/rbac_engineer_cannot_grant_pto
        """
        sc = setup_program_with_grid("RB1")
        ctx = add_customer_account(sc, "1")
        # Build every PTO gate green without granting: screens, exchange,
        # passed inspection.
        app = drive_to_screen_passed(sc, ctx, size=10_000,
                                     production=15_000_000)
        schedule_and_complete_exchange(app["id"])
        schedule_and_pass_inspection(ctx, app["id"])

        resp = api.grant_pto(app["id"], ENGINEER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        app_after = validate_success(api.get_application(app["id"], ADMIN))
        assert app_after["application_status"] == "SCREEN_PASSED"

    def test_technician_cannot_screen_applications(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role per
        the endpoint table in §4; an authenticated user who attempts an
        operation outside their role is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §2.10: "Every request is evaluated against an ordered pipeline of
        checks, and when several checks could reject the same request, the
        earliest check in this order determines the error returned."

        Design: Corner/rbac/rbac_technician_cannot_screen_applications
        """
        sc = setup_program_with_grid("RB2", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        # The application is also in the wrong state for screening; the role
        # check (second) must fire before the state check (eighth).
        resp = api.create_screening_report({"application_id": app["id"]},
                                           TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_coordinator_cannot_create_tariff(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role per
        the endpoint table in §4; an authenticated user who attempts an
        operation outside their role is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §4: "| POST | `/tariff-schedules` | Create a tariff window for a
        program | ProgramAdministrator |"

        Design: Corner/rbac/rbac_coordinator_cannot_create_tariff
        """
        program = create_program("RB3")
        resp = api.create_tariff_schedule(
            {
                "program_id": program["id"],
                "schedule_code": "NOPE",
                "effective_from": "2026-01-01T00:00:00Z",
                "import_rate_millicents_per_kwh": 30_000,
                "export_rate_millicents_per_kwh": 12_000,
                "net_surplus_rate_millicents_per_kwh": 4_500,
            },
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_coordinator_cannot_record_inspection_result(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role per
        the endpoint table in §4; an authenticated user who attempts an
        operation outside their role is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §4: "| POST | `/inspections/{inspection_id}/record-result` |
        Record an inspection outcome | Inspector |"

        Design: Corner/rbac/rbac_coordinator_cannot_record_inspection_result
        """
        sc = setup_program_with_grid("RB4")
        ctx = add_customer_account(sc, "1")
        app = drive_to_screen_passed(sc, ctx, size=10_000,
                                     production=15_000_000)
        schedule_and_complete_exchange(app["id"])
        inspection = get_success_data(api.create_inspection(
            {"application_id": app["id"],
             "scheduled_date": "2026-08-05T09:00:00Z"}, ctx["applicant"]))
        set_clock("2026-08-06T00:00:00Z")

        resp = api.record_inspection_result(
            inspection["id"],
            {"outcome": "PASSED", "occurred_at": "2026-08-05T10:00:00Z"},
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        inspection_after = validate_success(
            api.get_inspection(inspection["id"], ADMIN))
        assert inspection_after["inspection_status"] == "SCHEDULED"

    def test_applicant_cannot_review_own_documents(self, api):
        """PRD §2.10: "Second, the role's permission to invoke the endpoint
        (`ERR_FORBIDDEN_ROLE`). Third, for applicant-scoped mutating endpoints,
        ownership of the target resource (`ERR_FORBIDDEN_OWNERSHIP`)."
        PRD §4: "| POST | `/documents/{document_id}/review` | Accept or reject
        an uploaded document | InterconnectionCoordinator |"

        Design: Corner/rbac/rbac_applicant_cannot_review_own_documents
        """
        sc = setup_program_with_grid("RB5", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)
        doc = get_success_data(api.create_document(
            create_document_payload(app["id"], doc_type="SITE_PLAN",
                                    title="site"), ctx["applicant"]))
        # Even the owning applicant hits the role wall first.
        resp = api.review_document(doc["id"], {"outcome": "ACCEPTED"},
                                   ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_applicant_shared_read_access(self, api):
        """PRD §4: "| GET | `/programs/{program_id}` | Get a program | Any |"

        Design: Corner/rbac/rbac_applicant_shared_read_access
        """
        program = create_program("RB6")
        customer = get_success_data(api.create_customer(
            {"full_name": "RB6 Cust", "email": "rb6@example.com"}, ADMIN))
        applicant = build_user_headers(customer["id"], "Applicant")
        data = validate_success(api.get_program(program["id"], applicant))
        assert data["id"] == program["id"]
