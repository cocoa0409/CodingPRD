"""Authentication and role-based access control, the error envelope, and
identifier-resolution 404s (PRD §2.1, §2.2, §2.9, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_crew,
    create_cycle_payload,
    create_pole,
    create_treatment_order,
    make_contractor_headers,
    schedule_treatment,
    schedule_treatment_payload,
    setup_open_cycle_with_task,
    setup_submitted_joint_use_task,
    submit_task,
    validate_error,
    validate_success,
    get_treatment,
    get_task,
)

_PM = TEST_USERS["program_manager_headers"]


class TestAuthentication:
    def test_unauthenticated_missing_headers_returns_401(self, api):
        """PRD §2.1: "Each request must include `X-User-ID` to identify the acting
        party and `X-User-Role` to specify their operational capacity. The system
        recognizes exactly five roles, spelled precisely as follows: `ProgramManager`,
        `Inspector`, `QAReviewer`, `Contractor`, and `AttacherRep`. A request missing
        either header, or carrying a role value outside this set, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_missing_headers_returns_401
        """
        resp = api.list_backlog_snapshots(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleDenial:
    def test_inspector_cannot_create_cycle_forbidden(self, api, inspector_headers):
        """PRD §2.1: "Access to specific operations is further restricted by role; an
        authenticated caller attempting an operation outside their role's remit is
        rejected with `ERR_FORBIDDEN`."
        PRD §4: POST `/pole-program/inspection-cycles` is authorized for
        `ProgramManager` only.

        Design: Corner/validations/inspector_cannot_create_cycle_forbidden
        """
        resp = api.create_inspection_cycle(
            create_cycle_payload(year=2026, cycle_length_years=10, sample_pct=50),
            inspector_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_contractor_cannot_qa_review_forbidden(self, api):
        """PRD §2.1: "The `QAReviewer` decides quality reviews on both inspection tasks
        and treatment orders", and "an authenticated caller attempting an operation
        outside their role's remit is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/contractor_cannot_qa_review_forbidden
        """
        crew = create_crew(crew_code="CR-RB")
        _, _, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-RB", "species": "LARCH",
                            "original_class": "2", "install_date": "2001-05-01",
                            "gis_tag": "RURAL", "height_ft": 35}
        )
        submit_task(task["id"], shell_thickness_in=2.25, sound_wood_pct=100,
                    decay_pocket_depth_in=0.0, moisture_pct=20)
        resp = api.qa_review_inspection_task(
            task["id"], {"decision": "ACCEPT"}, make_contractor_headers(crew["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        assert get_task(task["id"])["status"] == "SUBMITTED"

    def test_attacher_cannot_adjudicate_audit_forbidden(self, api, attacher_rep_headers):
        """PRD §2.1: "The `AttacherRep` is a joint-use attacher representative who
        responds to violation notices by marking them cured"; adjudication is a
        `ProgramManager` act, so the AttacherRep attempt "is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/attacher_cannot_adjudicate_audit_forbidden
        """
        _, _, _, audit = setup_submitted_joint_use_task(
            found_attachment_count=2, declared=1,
            pole_overrides={"pole_number": "P-AT"},
        )
        resp = api.adjudicate_attachment_audit(audit["id"], attacher_rep_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        after = validate_success(api.get_attachment_audit(audit["id"], _PM))
        assert after["audit_status"] == "SUBMITTED"

    def test_contractor_apply_other_crews_order_forbidden(self, api):
        """PRD §2.1: "a `Contractor` may apply only a treatment order whose `crew_id`
        equals the caller's `X-User-ID`, and any mismatch is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/contractor_apply_other_crews_order_forbidden
        """
        crew_a = create_crew(crew_code="CR-A")
        crew_b = create_crew(crew_code="CR-B")
        pole = create_pole(pole_number="P-OC", species="LARCH", original_class="2",
                           install_date="2001-05-01", gis_lat=46.0, gis_lon=-121.0,
                           gis_tag="RURAL", height_ft=35)
        order = create_treatment_order(pole["id"])
        schedule_treatment(order["id"], crew_a["id"])
        resp = api.apply_treatment_work_order(
            order["id"], make_contractor_headers(crew_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        after = get_treatment(order["id"])
        assert after["status"] == "SCHEDULED"
        assert after["applied_at"] is None


class TestErrorEnvelope:
    def test_not_found_error_envelope_shape(self, api, program_manager_headers):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/endpoints/not_found_error_envelope_shape
        """
        resp = api.get_inspection_task(NON_EXISTENT_UUID, program_manager_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body.get("response_type") == "error"
        meta = body.get("meta", {})
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in meta
        error_data = validate_error(resp, ApiErrorId.ERR_TASK_NOT_FOUND)
        assert isinstance(error_data["message"], str) and error_data["message"].strip()


class TestIdentifierResolution:
    def test_qa_review_bogus_task_returns_404(self, api, qa_reviewer_headers):
        """PRD §2.9: "Each unresolved identifier maps to its resource-specific error:
        `ERR_POLE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_TASK_NOT_FOUND`,
        `ERR_TREATMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND`."

        Design: Corner/errors/qa_review_bogus_task_returns_404
        """
        resp = api.qa_review_inspection_task(
            NON_EXISTENT_UUID, {"decision": "ACCEPT"}, qa_reviewer_headers
        )
        validate_error(resp, ApiErrorId.ERR_TASK_NOT_FOUND)

    def test_adjudicate_bogus_claim_returns_404(self, api, program_manager_headers):
        """PRD §2.9: "Each unresolved identifier maps to its resource-specific error:
        `ERR_POLE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_TASK_NOT_FOUND`,
        `ERR_TREATMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND`."

        Design: Corner/errors/adjudicate_bogus_claim_returns_404
        """
        resp = api.adjudicate_warranty_claim(
            NON_EXISTENT_UUID, {"outcome": "HONOR"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)

    def test_mark_cured_bogus_audit_returns_404(self, api, attacher_rep_headers):
        """PRD §2.9: "Each unresolved identifier maps to its resource-specific error:
        `ERR_POLE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_TASK_NOT_FOUND`,
        `ERR_TREATMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND`."

        Design: Corner/errors/mark_cured_bogus_audit_returns_404
        """
        resp = api.mark_cured_attachment_audit(NON_EXISTENT_UUID, attacher_rep_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_FOUND)

    def test_schedule_bogus_order_returns_404(self, api, program_manager_headers):
        """PRD §2.9: "the system validates their existence in a sequential,
        left-to-right order and rejects the request immediately with the 404
        corresponding to the first identifier that does not resolve."

        Design: Corner/errors/schedule_bogus_order_returns_404
        """
        crew = create_crew(crew_code="CR-NF")
        resp = api.schedule_treatment_work_order(
            NON_EXISTENT_UUID,
            schedule_treatment_payload(crew["id"]),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TREATMENT_NOT_FOUND)
