"""Punch list item cycle and record document lifecycle."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_project,
    create_report_issued_visit,
    create_punch_list_item,
    create_accepted_record_document,
    set_clock,
    make_firm_admin_headers,
    make_architect_headers,
    make_contractor_headers,
)

SOV_A_ONLY = [{"line_code": "A", "description": "Concrete",
               "scheduled_value_cents": 10000000}]


def _project_with_punch_item(api, description="Paint touch-up lobby",
                             location="Level 1 lobby"):
    project = create_active_project(sov_lines=SOV_A_ONLY)
    set_clock("2026-08-20T09:00:00Z")
    visit, _ = create_report_issued_visit(
        project["id"], visit_date="2026-08-20", purpose="PUNCH_INSPECTION",
        conformance_summary="MINOR_DEVIATIONS",
    )
    item = create_punch_list_item(
        project["id"], visit["id"], description=description, location=location,
    )
    return project, visit, item


class TestPunchItemVerifyReopenCycle:
    def test_reopen_verified_item_increments_reopen_count(self, api):
        """PRD 3.7: "A `VERIFIED` item can also be reopened — the machine is
        deliberately cyclic — but only while the project is `ACTIVE` or
        `SUBSTANTIAL_COMPLETION_ACHIEVED`" and "Every reopen increments
        `reopen_count` by one."

        Design: Difficulty/non_linear_state_machine/punch_item_verify_reopen_cycle
        """
        project, visit, item = _project_with_punch_item(api)
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        api.claim_punch_item_complete(item["id"], contractor_headers)
        verified = validate_success(
            api.verify_punch_item(item["id"], make_architect_headers()), 200)
        assert verified["status"] == "VERIFIED"
        reopened = validate_success(api.reopen_punch_item(
            item["id"], {"reason": "touch-up peeled"}, make_architect_headers(),
        ), 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1

    def test_full_cycle_lands_verified_with_reopen_count_one(self, api):
        """PRD 3.7: "From `OPEN` or `REOPENED`, a `Contractor` claims completion,
        moving the item to `CLAIMED_COMPLETE`. An `ArchitectCA` then verifies the
        claim, moving `CLAIMED_COMPLETE` to `VERIFIED`".

        Design: Difficulty/non_linear_state_machine/punch_item_verify_reopen_cycle
        """
        project, visit, item = _project_with_punch_item(api)
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        api.claim_punch_item_complete(item["id"], contractor_headers)
        api.verify_punch_item(item["id"], make_architect_headers())
        api.reopen_punch_item(item["id"], {"reason": "touch-up peeled"},
                              make_architect_headers())
        api.claim_punch_item_complete(item["id"], contractor_headers)
        final = validate_success(
            api.verify_punch_item(item["id"], make_architect_headers()), 200)
        assert final["status"] == "VERIFIED"
        assert final["reopen_count"] == 1


class TestVerifyOpenPunchItem:
    def test_verify_open_punch_item_returns_invalid_state(self, api):
        """PRD 3.7: "Claiming from a state other than `OPEN` or `REOPENED`,
        verifying from a state other than `CLAIMED_COMPLETE`, or reopening from a
        state other than `CLAIMED_COMPLETE` or `VERIFIED` fails with
        `ERR_PUNCH_ITEM_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/verify_open_punch_item_returns_invalid_state
        """
        project, visit, item = _project_with_punch_item(
            api, description="Paint touch-up", location="Corridor 2",
        )
        resp = api.verify_punch_item(item["id"], make_architect_headers())
        validate_error(resp, ApiErrorId.ERR_PUNCH_ITEM_INVALID_STATE, 409)
        current = get_success_data(
            api.get_punch_list_item(item["id"], make_architect_headers()))
        assert current["status"] == "OPEN"


class TestPunchVisitValidity:
    def test_punch_item_with_non_inspection_visit_returns_422(self, api):
        """PRD 3.7: "The referenced visit must be a `PUNCH_INSPECTION` visit in
        `REPORT_ISSUED` on the same project, else `ERR_PUNCH_VISIT_INVALID`
        (HTTP 422)."

        Design: Corner/validations/punch_item_with_non_inspection_visit_returns_422
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        set_clock("2026-08-20T09:00:00Z")
        visit, _ = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PROGRESS_OBSERVATION",
        )
        resp = api.create_punch_list_item(
            {"project_id": project["id"], "raised_visit_id": visit["id"],
             "description": "Nail pops", "location": "Unit 3B"},
            make_architect_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_PUNCH_VISIT_INVALID, 422)


class TestRecordDocuments:
    def test_duplicate_record_document_type_returns_409(self, api):
        """PRD 3.7: "Only one live document may exist per project and document
        type: creation is blocked with `ERR_DUPLICATE_RECORD_DOCUMENT` (HTTP 409)
        while another document of the same project and type sits in `SUBMITTED`,
        `RETURNED_FOR_CORRECTION`, or `ACCEPTED`."

        Design: Corner/validations/duplicate_record_document_type_returns_409
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        first = validate_success(api.create_record_document(
            {"project_id": project["id"], "doc_type": "AS_BUILT"}, contractor_headers,
        ), 201)
        resp = api.create_record_document(
            {"project_id": project["id"], "doc_type": "AS_BUILT"}, contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RECORD_DOCUMENT, 409)
        current = get_success_data(
            api.get_record_document(first["id"], make_firm_admin_headers()))
        assert current["status"] == "SUBMITTED"

    def test_resubmit_submitted_record_document_returns_invalid_state(self, api):
        """PRD 3.7: "Reviewing a document not in `SUBMITTED`, or resubmitting one
        not in `RETURNED_FOR_CORRECTION`, fails with
        `ERR_RECORD_DOCUMENT_INVALID_STATE` (HTTP 409)."

        Design: Corner/validations/resubmit_submitted_record_document_returns_invalid_state
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        document = validate_success(api.create_record_document(
            {"project_id": project["id"], "doc_type": "AS_BUILT"}, contractor_headers,
        ), 201)
        resp = api.resubmit_record_document(document["id"], contractor_headers)
        validate_error(resp, ApiErrorId.ERR_RECORD_DOCUMENT_INVALID_STATE, 409)
        current = get_success_data(
            api.get_record_document(document["id"], make_firm_admin_headers()))
        assert current["revision_number"] == 1
