"""Project closeout gates: substantial completion, final completion, close."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_project,
    create_report_issued_visit,
    create_payment_application,
    create_punch_list_item,
    accept_all_record_documents,
    setup_substantial_completion_project,
    setup_final_completion_project,
    set_clock,
    make_firm_admin_headers,
    make_architect_headers,
    make_contractor_headers,
)

SOV_A_ONLY = [{"line_code": "A", "description": "Concrete",
               "scheduled_value_cents": 10000000}]


class TestSubstantialCompletionGate:
    def test_achieve_substantial_without_punch_inspection_returns_409(self, api):
        """PRD 3.7: "Substantial completion is determined by an `ArchitectCA` and
        requires the project in `ACTIVE` (else `ERR_PROJECT_NOT_ACTIVE`) and at
        least one site visit on the project with `purpose` `PUNCH_INSPECTION` in
        `REPORT_ISSUED` status (else `ERR_PUNCH_INSPECTION_REQUIRED`, HTTP 409)."

        Design: Corner/validations/achieve_substantial_without_punch_inspection_returns_409
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        resp = api.achieve_substantial_completion(project["id"], make_architect_headers())
        validate_error(resp, ApiErrorId.ERR_PUNCH_INSPECTION_REQUIRED, 409)
        current = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert current["status"] == "ACTIVE"


class TestFinalCompletionGateOrdering:
    def test_achieve_final_on_active_project_returns_not_substantial(self, api):
        """PRD 3.7: "The project must be in `SUBSTANTIAL_COMPLETION_ACHIEVED` — an
        attempt from `ACTIVE` reports `ERR_PROJECT_NOT_SUBSTANTIAL` (HTTP 409)."

        Design: Corner/validations/achieve_final_on_active_project_returns_not_substantial
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        resp = api.achieve_final_completion(project["id"], make_architect_headers())
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_SUBSTANTIAL, 409)

    def test_achieve_final_without_record_documents_returns_409(self, api):
        """PRD 3.7: "each of the four document types — `AS_BUILT`, `OM_MANUAL`,
        `WARRANTY`, and `TEST_REPORT` — must have at least one `ACCEPTED` record
        document (else `ERR_RECORD_DOCUMENTS_INCOMPLETE`); when both would fail,
        the punch-item gate is reported first."

        Design: Corner/validations/achieve_final_without_record_documents_returns_409
        """
        project, _visit, _report = setup_substantial_completion_project(
            sov_lines=SOV_A_ONLY)
        resp = api.achieve_final_completion(project["id"], make_architect_headers())
        validate_error(resp, ApiErrorId.ERR_RECORD_DOCUMENTS_INCOMPLETE, 409)
        current = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert current["status"] == "SUBSTANTIAL_COMPLETION_ACHIEVED"


class TestFinalCompletionRequiresAllPunchVerified:
    def _substantial_project_with_claimed_punch(self, api):
        """SUBSTANTIAL_COMPLETION_ACHIEVED project, all four record documents
        ACCEPTED, and one CLAIMED_COMPLETE punch item raised from the inspection.

        The punch item is raised and claimed while the project is still ACTIVE:
        PRD 3.1 requires punch-list-item creation against an ACTIVE project
        ("Creating a submittal, site visit, RFI, payment application, change
        order, or punch list item requires the project to be `ACTIVE`").
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        set_clock("2026-08-20T09:00:00Z")
        visit, _ = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PUNCH_INSPECTION",
            conformance_summary="MINOR_DEVIATIONS",
        )
        item = create_punch_list_item(
            project["id"], visit["id"],
            description="Caulk joint at entry", location="Entry",
        )
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        api.claim_punch_item_complete(item["id"], contractor_headers)
        accept_all_record_documents(project["id"])
        resp = api.achieve_substantial_completion(project["id"], make_architect_headers())
        project = get_success_data(resp)
        return project, item

    def test_open_punch_item_blocks_final_completion(self, api):
        """PRD 3.7: "no punch list item on the project may remain in `OPEN`,
        `CLAIMED_COMPLETE`, or `REOPENED` (else `ERR_OPEN_PUNCH_ITEMS_REMAIN`)".

        Design: Difficulty/cross_entity_state_dependency/final_completion_requires_all_punch_verified
        """
        project, item = self._substantial_project_with_claimed_punch(api)
        resp = api.achieve_final_completion(project["id"], make_architect_headers())
        validate_error(resp, ApiErrorId.ERR_OPEN_PUNCH_ITEMS_REMAIN, 409)

    def test_verifying_last_punch_item_unblocks_final_completion(self, api):
        """PRD 3.7: "Success moves the project to `FINAL_COMPLETION_ACHIEVED`."

        Design: Difficulty/cross_entity_state_dependency/final_completion_requires_all_punch_verified
        """
        project, item = self._substantial_project_with_claimed_punch(api)
        verified = validate_success(
            api.verify_punch_item(item["id"], make_architect_headers()), 200)
        assert verified["status"] == "VERIFIED"
        resp = api.achieve_final_completion(project["id"], make_architect_headers())
        project = validate_success(resp, 200)
        assert project["status"] == "FINAL_COMPLETION_ACHIEVED"


class TestCloseGates:
    def test_close_before_final_completion_returns_not_final(self, api):
        """PRD 3.7: "The project must be in `FINAL_COMPLETION_ACHIEVED` (else
        `ERR_PROJECT_NOT_FINAL`)".

        Design: Corner/validations/close_before_final_completion_returns_not_final
        """
        project, _visit, _report = setup_substantial_completion_project(
            sov_lines=SOV_A_ONLY)
        resp = api.close_project(project["id"], make_firm_admin_headers())
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FINAL, 409)
        current = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert current["status"] == "SUBSTANTIAL_COMPLETION_ACHIEVED"

    def test_close_with_open_pay_app_returns_409(self, api):
        """PRD 3.7: "no payment application may remain in `SUBMITTED` or
        `REJECTED` (else `ERR_OPEN_PAYMENT_APPLICATIONS`)".

        Design: Corner/validations/close_with_open_pay_app_returns_409
        """
        # Build a project whose payment application was REJECTED while ACTIVE,
        # then drive the project to FINAL_COMPLETION_ACHIEVED.
        project = create_active_project(sov_lines=SOV_A_ONLY)
        set_clock("2026-08-20T09:00:00Z")
        visit1, _ = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PAYMENT_VERIFICATION",
        )
        application = create_payment_application(
            project["id"], visit1["id"], period_ending_date="2026-08-31",
        )
        api.reject_payment_application(
            application["id"], {"reason": "missing lien waivers"},
            make_architect_headers(),
        )
        set_clock("2026-08-21T09:00:00Z")
        visit2, _ = create_report_issued_visit(
            project["id"], visit_date="2026-08-21", purpose="PUNCH_INSPECTION",
        )
        resp = api.achieve_substantial_completion(project["id"], make_architect_headers())
        project = get_success_data(resp)
        accept_all_record_documents(project["id"])
        resp = api.achieve_final_completion(project["id"], make_architect_headers())
        project = get_success_data(resp)
        assert project["status"] == "FINAL_COMPLETION_ACHIEVED"
        resp = api.close_project(project["id"], make_firm_admin_headers())
        validate_error(resp, ApiErrorId.ERR_OPEN_PAYMENT_APPLICATIONS, 409)
        current = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert current["status"] == "FINAL_COMPLETION_ACHIEVED"
        app_current = get_success_data(
            api.get_payment_application(application["id"], make_firm_admin_headers()))
        assert app_current["status"] == "REJECTED"

    def test_close_with_open_invoice_returns_409(self, api):
        """PRD 3.7: "no additional-service invoice may remain in `DRAFT`,
        `ISSUED`, `OWNER_APPROVED`, or `DISPUTED` (else `ERR_OPEN_INVOICES`)".

        Design: Corner/validations/close_with_open_invoice_returns_409
        """
        from test_helpers import create_draft_invoice
        project = create_active_project(sov_lines=SOV_A_ONLY, grace_days=5)
        set_clock("2026-11-05T09:00:00Z")
        invoice = create_draft_invoice(project["id"], "2026-10-01", "2026-10-31")
        visit, _ = create_report_issued_visit(
            project["id"], visit_date="2026-11-05", purpose="PUNCH_INSPECTION",
        )
        resp = api.achieve_substantial_completion(project["id"], make_architect_headers())
        project = get_success_data(resp)
        accept_all_record_documents(project["id"])
        resp = api.achieve_final_completion(project["id"], make_architect_headers())
        project = get_success_data(resp)
        resp = api.close_project(project["id"], make_firm_admin_headers())
        validate_error(resp, ApiErrorId.ERR_OPEN_INVOICES, 409)
        current = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert current["status"] == "FINAL_COMPLETION_ACHIEVED"
        invoice_current = get_success_data(
            api.get_additional_service_invoice(invoice["id"], make_firm_admin_headers()))
        assert invoice_current["status"] == "DRAFT"
