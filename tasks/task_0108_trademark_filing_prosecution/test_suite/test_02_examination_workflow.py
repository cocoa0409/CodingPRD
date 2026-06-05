"""Examination loop: office-action issuance, the OFFICE_ACTION_ISSUED <->
UNDER_EXAMINATION revision cycle, response timeliness boundaries, and the
minimum-goods file gate.

Sources: Difficulty/non_linear_state_machine, Difficulty/boundary_precision_check,
Corner/state_machines, Corner/calculations.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    setup_base_parties,
    setup_examined_application,
    setup_application_with_outstanding_oa,
    create_draft_application,
    issue_office_action,
    respond_to_office_action,
    set_clock,
    examiner_headers,
)


class TestOfficeActionRevisionLoop:
    """The application cycles UNDER_EXAMINATION -> OFFICE_ACTION_ISSUED ->
    UNDER_EXAMINATION -> OFFICE_ACTION_ISSUED, returning twice; office_action_round
    reaches 2."""

    def _setup_after_first_response(self):
        base = setup_application_with_outstanding_oa(
            class_numbers=(9,), ground="IDENTIFICATION_INDEFINITE", is_final=False,
            mark_text="LOOPER")
        # Respond to the first OA -> back to UNDER_EXAMINATION.
        respond_to_office_action(
            base["office_action"]["id"], base["att_headers"],
            argument_text="amended identification", amends_identification=True)
        return base

    def test_second_office_action_round_number_is_2(self, api):
        """PRD §3.3: "The server assigns the action a round_number equal to the
        application's current office_action_round plus one (so the first action is
        round 1, the second round 2, and so on)"

        Design: Difficulty/non_linear_state_machine/application_office_action_revision_loop_cycle
        """
        base = self._setup_after_first_response()
        oa2 = validate_success(api.create_office_action(
            {"application_id": base["application"]["id"],
             "ground": "IDENTIFICATION_INDEFINITE", "is_final": True},
            examiner_headers()), 201)
        assert oa2["round_number"] == 2, (
            f"second office action should be round 2, got {oa2['round_number']}")

    def test_application_returns_to_office_action_issued_with_round_2(self, api):
        """PRD §3.3: "While an application is UNDER_EXAMINATION, an examiner may
        issue an OfficeAction against it, which moves the application to
        OFFICE_ACTION_ISSUED."
        PRD §3.3: "Issuing the action increments the application's
        office_action_round by one"

        Design: Difficulty/non_linear_state_machine/application_office_action_revision_loop_cycle
        """
        base = self._setup_after_first_response()
        validate_success(api.create_office_action(
            {"application_id": base["application"]["id"],
             "ground": "IDENTIFICATION_INDEFINITE", "is_final": True},
            examiner_headers()), 201)
        app = validate_success(api.get_application(
            base["application"]["id"], examiner_headers()), 200)
        assert app["status"] == "OFFICE_ACTION_ISSUED"
        assert app["office_action_round"] == 2, (
            f"office_action_round should be 2 after the loop, got {app['office_action_round']}")


class TestFinalOfficeActionResponseBoundary:
    """A FINAL OfficeAction grants zero grace; a response one day after the
    deadline is rejected ERR_RESPONSE_DEADLINE_PASSED."""

    def test_final_action_response_one_day_late_rejected(self, api):
        """PRD §3.3: "For a final action, any submission after the response_deadline
        is refused with ERR_RESPONSE_DEADLINE_PASSED."

        Design: Difficulty/boundary_precision_check/final_office_action_response_one_day_late_rejected
        """
        base = setup_application_with_outstanding_oa(
            class_numbers=(9,), ground="SPECIMEN_DEFECT", is_final=True, mark_text="LATE")
        # Issued 2026-01-01, deadline 2026-04-01; respond one day late.
        set_clock("2026-04-02T00:00:00Z")
        res = api.create_office_action_response(
            {"office_action_id": base["office_action"]["id"], "argument_text": "late remarks"},
            base["att_headers"])
        validate_error(res, "ERR_RESPONSE_DEADLINE_PASSED")

    def test_final_action_response_on_deadline_accepted(self, api):
        """PRD §3.3: "so days_late is 0 when the response arrives on or before the
        deadline."
        PRD §3.3: "Accepting a response sets the answered office action's status to
        RESPONDED and marks its docket deadline MET."

        Design: Difficulty/boundary_precision_check/final_office_action_response_one_day_late_rejected
        """
        base = setup_application_with_outstanding_oa(
            class_numbers=(9,), ground="SPECIMEN_DEFECT", is_final=True, mark_text="ONDL")
        # Deadline is exactly 2026-04-01 (issued 2026-01-01 + 90 days).
        set_clock("2026-04-01T00:00:00Z")
        resp = validate_success(api.create_office_action_response(
            {"office_action_id": base["office_action"]["id"], "argument_text": "timely remarks"},
            base["att_headers"]), 201)
        assert resp["days_late"] == 0
        oa = validate_success(api.get_office_action(
            base["office_action"]["id"], examiner_headers()), 200)
        assert oa["status"] == "RESPONDED"


class TestFileWithZeroGoodsServices:
    """An application with zero GoodsServicesItem (class_count == 0) is rejected
    at file time with ERR_NO_GOODS_SERVICES."""

    def test_file_application_with_no_items_rejected(self, api):
        """PRD §3.2: "the minimum-goods check — the application must carry at least
        one goods/services item, that is its class_count must be at least 1,
        otherwise the filing is refused with ERR_NO_GOODS_SERVICES."

        Design: Difficulty/boundary_precision_check/file_application_with_zero_classes_empty_set
        """
        base = setup_base_parties(class_numbers=())
        att_headers = base["att_headers"]
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="EMPTY", filing_basis="USE", filing_tier="TEAS_STANDARD")
        res = api.file_application(app["id"], att_headers)
        validate_error(res, "ERR_NO_GOODS_SERVICES")

    def test_file_with_one_item_succeeds_after_empty_rejected(self, api):
        """PRD §3.2: "the minimum-goods check — the application must carry at least
        one goods/services item, that is its class_count must be at least 1,
        otherwise the filing is refused with ERR_NO_GOODS_SERVICES."

        Design: Difficulty/boundary_precision_check/file_application_with_zero_classes_empty_set
        """
        from test_helpers import add_item
        base = setup_base_parties(class_numbers=(9,))
        att_headers = base["att_headers"]
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="NONEMPTY", filing_basis="USE", filing_tier="TEAS_STANDARD")
        # zero-item file fails, one-item file succeeds -> the count==0 edge is the gate.
        validate_error(api.file_application(app["id"], att_headers), "ERR_NO_GOODS_SERVICES")
        add_item(app["id"], base["nice_classes"][0]["id"], att_headers)
        filed = validate_success(api.file_application(app["id"], att_headers), 200)
        assert filed["status"] == "FILED"


class TestExaminationStateGuards:
    """Corner cases on the examination transitions."""

    def test_assign_examination_from_draft_rejected(self, api):
        """PRD §3.2: "An examiner picks up a FILED application and assigns it for
        examination, moving it to UNDER_EXAMINATION."
        PRD §3.8: "the target resource must be in a state from which the requested
        transition is permitted, else ERR_INVALID_STATE."

        Design: Corner/state_machines/assign_examination_from_draft_returns_invalid_state
        """
        from test_helpers import add_item
        base = setup_base_parties(class_numbers=(9,))
        att_headers = base["att_headers"]
        app = create_draft_application(
            base["applicant"]["id"], att_headers, attorney_id=base["attorney"]["id"],
            mark_text="DRAFTONLY", filing_basis="USE", filing_tier="TEAS_STANDARD")
        add_item(app["id"], base["nice_classes"][0]["id"], att_headers)
        res = api.assign_examination(app["id"], examiner_headers())
        validate_error(res, "ERR_INVALID_STATE")
        app_after = validate_success(api.get_application(app["id"], examiner_headers()), 200)
        assert app_after["status"] == "DRAFT"

    def test_respond_twice_to_office_action_rejected(self, api):
        """PRD §3.3: "The response may be filed only while the latest office
        action's status is OUTSTANDING; a response submitted against an action
        already advanced past OUTSTANDING is refused with ERR_ACTION_ALREADY_CLOSED."

        Design: Corner/state_machines/respond_twice_to_office_action_returns_already_closed
        """
        base = setup_application_with_outstanding_oa(
            class_numbers=(9,), ground="IDENTIFICATION_INDEFINITE", is_final=False,
            mark_text="TWICE")
        respond_to_office_action(
            base["office_action"]["id"], base["att_headers"], argument_text="first response")
        res = api.create_office_action_response(
            {"office_action_id": base["office_action"]["id"], "argument_text": "second response"},
            base["att_headers"])
        validate_error(res, "ERR_ACTION_ALREADY_CLOSED")

    def test_on_time_response_days_late_zero_and_responded(self, api):
        """PRD §3.3: "so days_late is 0 when the response arrives on or before the
        deadline."
        PRD §3.3: "Accepting a response sets the answered office action's status to
        RESPONDED and marks its docket deadline MET."

        Design: Corner/calculations/office_action_response_on_time_days_late_zero
        """
        base = setup_application_with_outstanding_oa(
            class_numbers=(9,), ground="MERELY_DESCRIPTIVE", is_final=False, mark_text="ONTIME")
        set_clock("2026-04-01T00:00:00Z")  # exactly the 90-day deadline
        resp = validate_success(api.create_office_action_response(
            {"office_action_id": base["office_action"]["id"], "argument_text": "timely remarks"},
            base["att_headers"]), 201)
        assert resp["days_late"] == 0
        oa = validate_success(api.get_office_action(
            base["office_action"]["id"], examiner_headers()), 200)
        assert oa["status"] == "RESPONDED"
