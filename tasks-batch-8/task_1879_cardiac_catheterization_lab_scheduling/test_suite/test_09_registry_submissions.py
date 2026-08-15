"""Registry submissions: creation gate, completeness, submission window,
decisions, and the revision cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_radiation_record,
    assert_registry_submission,
    complete_case,
    create_cardiologist,
    create_circulating_nurse,
    create_recovery_bed,
    create_room,
    create_scrub_technologist,
    post_case,
    record_decision_payload,
    revise_payload,
    schedule_case,
    set_clock,
    setup_completed_workspace,
    setup_in_progress_workspace,
    setup_submission_workspace,
    staff_case,
    start_case,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHEDULER = TEST_USERS["scheduler_headers"]
REGISTRY = TEST_USERS["registry_coordinator_headers"]


class TestSubmissionCreationGate:
    def test_submission_create_blocked_while_case_in_progress(self, api):
        """PRD §3.9: "Once a case is `COMPLETED`, a `RegistryCoordinator` opens its
        registry submission; opening one for a case in any other state is refused
        with `ERR_CASE_INVALID_STATE`, and a case admits at most one submission — a
        second attempt is `ERR_DUPLICATE_SUBMISSION`."

        Design: Difficulty/cross_entity_state_dependency/submission_create_requires_case_completed
        """
        workspace = setup_in_progress_workspace()
        resp = api.create_registry_submission(workspace["case"]["id"], REGISTRY)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, expected_status=409)
        _, meta = validate_paginated(
            api.list_case_registry_submissions(workspace["case"]["id"], REGISTRY))
        assert meta["total_count"] == 0, "no submission persisted"

    def test_submission_create_after_completion_succeeds(self, api):
        """PRD §3.9: "Once a case is `COMPLETED`, a `RegistryCoordinator` opens its
        registry submission"
        PRD §3.9: "The submission opens in `DRAFT`, recorded against its case as
        `case_id`, with `submitted_at`, `decided_at`, `rejection_reason`, and
        `correction_note` all null, and its `completeness_pct` computed
        immediately."

        Design: Difficulty/cross_entity_state_dependency/submission_create_requires_case_completed
        """
        workspace = setup_completed_workspace()
        submission = validate_success(
            api.create_registry_submission(workspace["case"]["id"], REGISTRY), 201)
        assert_registry_submission(submission)
        assert submission["status"] == "DRAFT"
        assert submission["case_id"] == workspace["case"]["id"]
        assert submission["submitted_at"] is None
        assert submission["decided_at"] is None
        _, meta = validate_paginated(
            api.list_case_registry_submissions(workspace["case"]["id"], REGISTRY))
        assert meta["total_count"] == 1


class TestRevisionCycle:
    def test_submission_submit_and_rejection(self, api):
        """PRD §3.9: "Submitting moves a `DRAFT` submission to `SUBMITTED` behind
        three gates."
        PRD §3.9: "A successful submit stamps `submitted_at` from the logical clock
        and stores the refreshed `completeness_pct`."
        PRD §3.9: "An `outcome` of `REJECTED` requires a `rejection_reason` in the
        payload, and its absence fails with `ERR_INVALID_REQUEST`; the reason is
        stored and `decided_at` stamped."
        PRD §3.9: "The submission's `registry_name` is derived from the case's
        `procedure_type`: `NCDR_CATHPCI` for `DIAGNOSTIC_CATHETERIZATION`, `PCI`,
        and `STEMI_PCI`; `NCDR_ICD` for `DEVICE_IMPLANT`; and `NCDR_EP` for
        `EP_STUDY`."

        Design: Difficulty/non_linear_state_machine/registry_submission_revision_cycle
        """
        workspace = setup_submission_workspace(priority="ELECTIVE")
        submission = workspace["submission"]
        assert submission["registry_name"] == "NCDR_CATHPCI"  # PCI case

        submitted = validate_success(
            api.submit_registry_submission(submission["id"], REGISTRY))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["completeness_pct"] == pytest.approx(100.0, abs=1e-6)
        assert submitted["submitted_at"] is not None

        decided = validate_success(api.record_submission_decision(
            submission["id"],
            record_decision_payload("REJECTED",
                                    rejection_reason="missing lesion segment"),
            REGISTRY))
        assert decided["status"] == "REJECTED"
        assert decided["rejection_reason"] == "missing lesion segment"
        assert decided["decided_at"] is not None

    def test_rejected_submission_revision_returns_to_draft_and_resubmits(self, api):
        """PRD §3.9: "Revising carries a required `correction_note`, moves the
        submission `REJECTED` → `DRAFT` — again, only from `REJECTED`, else
        `ERR_SUBMISSION_INVALID_STATE` — stores the note, and clears `submitted_at`
        and `decided_at` to null, readying the submission for a fresh attempt."
        PRD §3.9: "The loop `DRAFT` → `SUBMITTED` → `REJECTED` → `DRAFT` may repeat
        as often as needed."

        Design: Difficulty/non_linear_state_machine/registry_submission_revision_cycle
        """
        workspace = setup_submission_workspace(priority="ELECTIVE")
        submission = workspace["submission"]
        validate_success(api.submit_registry_submission(submission["id"], REGISTRY))
        validate_success(api.record_submission_decision(
            submission["id"],
            record_decision_payload("REJECTED",
                                    rejection_reason="missing lesion segment"),
            REGISTRY))

        revised = validate_success(api.revise_registry_submission(
            submission["id"], revise_payload("added lesion segment"), REGISTRY))
        assert revised["status"] == "DRAFT", "cycle loops back to DRAFT"
        assert revised["submitted_at"] is None
        assert revised["decided_at"] is None
        assert revised["correction_note"] == "added lesion segment"

        resubmitted = validate_success(
            api.submit_registry_submission(submission["id"], REGISTRY))
        assert resubmitted["status"] == "SUBMITTED"


class TestRegistryNameDerivation:
    def test_registry_name_derived_from_procedure_type(self, api):
        """PRD §3.9: "The submission's `registry_name` is derived from the case's
        `procedure_type`: `NCDR_CATHPCI` for `DIAGNOSTIC_CATHETERIZATION`, `PCI`,
        and `STEMI_PCI`; `NCDR_ICD` for `DEVICE_IMPLANT`; and `NCDR_EP` for
        `EP_STUDY`."

        Design: Corner/calculations/registry_name_derived_from_procedure_type
        """
        physician = create_cardiologist()
        scrub_tech = create_scrub_technologist()
        nurse = create_circulating_nurse()
        room = create_room(room_name="Lab 1")
        bed1 = create_recovery_bed("Bed 1")
        bed2 = create_recovery_bed("Bed 2")

        case_d = post_case(physician["id"], patient_mrn="MRN-D",
                           procedure_type="DEVICE_IMPLANT")
        schedule_case(case_d["id"], room["id"], "2026-08-10T09:00:00Z",
                      bed_id=bed1["id"])
        staff_case(case_d["id"], scrub_tech["id"], nurse["id"])
        start_case(case_d["id"], physician["id"])
        add_radiation_record(case_d["id"], 20, 5)
        complete_case(case_d["id"], physician["id"])

        case_e = post_case(physician["id"], patient_mrn="MRN-E",
                           procedure_type="EP_STUDY")
        schedule_case(case_e["id"], room["id"], "2026-08-10T13:00:00Z",
                      bed_id=bed2["id"])
        staff_case(case_e["id"], scrub_tech["id"], nurse["id"])
        start_case(case_e["id"], physician["id"])
        add_radiation_record(case_e["id"], 30, 10)
        complete_case(case_e["id"], physician["id"])

        sub_d = validate_success(
            api.create_registry_submission(case_d["id"], REGISTRY), 201)
        sub_e = validate_success(
            api.create_registry_submission(case_e["id"], REGISTRY), 201)
        assert sub_d["registry_name"] == "NCDR_ICD"
        assert sub_e["registry_name"] == "NCDR_EP"


class TestCompletenessAndWindow:
    def test_registry_completeness_partial_and_submit_incomplete(self, api):
        """PRD §3.9: "Completeness scores the case against six required elements —
        seven for an `ELECTIVE` case. Always required: the `patient_mrn` is
        present; the `performing_physician_id` is set; `actual_start` is set;
        `actual_end` is set; at least one `RADIATION` dose entry is `ACTIVE`; and
        no device usage of the case remains `RESERVED`. Elective cases additionally
        require `auc_status` to be `DOCUMENTED`. The `completeness_pct` is the
        number of satisfied elements divided by the number required, expressed as a
        percentage and rounded half-up to one decimal place; it is evaluated when
        the submission is created and refreshed again at submit time."
        PRD §3.9: "Its completeness must be exactly 100.0 — anything less, even
        99.9, fails with `ERR_SUBMISSION_INCOMPLETE`."

        Design: Corner/calculations/registry_completeness_partial_and_submit_incomplete
        """
        # ELECTIVE case completed with NO radiation dose record: 6 of 7 elements.
        workspace = setup_submission_workspace(priority="ELECTIVE",
                                               with_radiation=False)
        submission = workspace["submission"]
        assert submission["completeness_pct"] == pytest.approx(85.7, abs=1e-6), \
            "6 of 7 required elements (missing an ACTIVE RADIATION entry)"
        resp = api.submit_registry_submission(submission["id"], REGISTRY)
        # PRD §3.9 names the error_id; the §5 catalogue pins no HTTP status for
        # it, so only the error_id is asserted here.
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_INCOMPLETE)
        current = validate_success(
            api.get_registry_submission(submission["id"], REGISTRY))
        assert current["status"] == "DRAFT"

    def test_submission_window_boundary_exactly_at_deadline(self, api):
        """PRD §3.9: "And the registry window must still be open: the deadline is
        thirty days after the case's `actual_end`, a current logical time falling
        strictly after that deadline is rejected with
        `ERR_SUBMISSION_WINDOW_EXPIRED`, and a submission landing exactly at the
        deadline is allowed."

        Design: Corner/calculations/submission_window_boundary_exactly_at_deadline
        """
        set_clock("2026-08-10T08:00:00Z")
        physician = create_cardiologist()
        scrub_tech = create_scrub_technologist()
        nurse = create_circulating_nurse()
        room = create_room(room_name="Lab 1")
        bed1 = create_recovery_bed("Bed 1")
        bed2 = create_recovery_bed("Bed 2")

        # Post and schedule both cases first (case A's completion frees the
        # staff for case B's assignments).
        case_a = post_case(physician["id"], patient_mrn="MRN-A")
        schedule_case(case_a["id"], room["id"], "2026-08-10T09:00:00Z",
                      bed_id=bed1["id"])
        staff_case(case_a["id"], scrub_tech["id"], nurse["id"])
        case_b = post_case(physician["id"], patient_mrn="MRN-B")
        schedule_case(case_b["id"], room["id"], "2026-08-10T12:00:00Z",
                      bed_id=bed2["id"])

        set_clock("2026-08-10T10:30:00Z")
        start_case(case_a["id"], physician["id"])
        add_radiation_record(case_a["id"], 10, 0)
        case_a = complete_case(case_a["id"], physician["id"])
        staff_case(case_b["id"], scrub_tech["id"], nurse["id"])
        start_case(case_b["id"], physician["id"])
        add_radiation_record(case_b["id"], 10, 0)
        case_b = complete_case(case_b["id"], physician["id"])
        # Both cases completed at the same logical instant: 2026-08-10T10:30:00Z.
        assert case_a["actual_end"] == case_b["actual_end"]

        sub_a = validate_success(
            api.create_registry_submission(case_a["id"], REGISTRY), 201)
        sub_b = validate_success(
            api.create_registry_submission(case_b["id"], REGISTRY), 201)

        # Exactly actual_end + 30 days: allowed.
        set_clock("2026-09-09T10:30:00Z")
        submitted_a = validate_success(
            api.submit_registry_submission(sub_a["id"], REGISTRY))
        assert submitted_a["status"] == "SUBMITTED"

        # One second past the deadline: rejected.
        set_clock("2026-09-09T10:30:01Z")
        resp = api.submit_registry_submission(sub_b["id"], REGISTRY)
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_WINDOW_EXPIRED,
                       expected_status=422)
        current_b = validate_success(
            api.get_registry_submission(sub_b["id"], REGISTRY))
        assert current_b["status"] == "DRAFT"


class TestDecisionAndReviseGates:
    def test_duplicate_submission_returns_conflict(self, api):
        """PRD §3.9: "Once a case is `COMPLETED`, a `RegistryCoordinator` opens its
        registry submission; opening one for a case in any other state is refused
        with `ERR_CASE_INVALID_STATE`, and a case admits at most one submission — a
        second attempt is `ERR_DUPLICATE_SUBMISSION`."

        Design: Corner/validations/duplicate_submission_returns_conflict
        """
        workspace = setup_submission_workspace()
        resp = api.create_registry_submission(workspace["case"]["id"], REGISTRY)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBMISSION,
                       expected_status=409)
        _, meta = validate_paginated(
            api.list_case_registry_submissions(workspace["case"]["id"], REGISTRY))
        assert meta["total_count"] == 1

    def test_record_decision_rejected_missing_reason_returns_invalid_request(self, api):
        """PRD §3.9: "An `outcome` of `REJECTED` requires a `rejection_reason` in
        the payload, and its absence fails with `ERR_INVALID_REQUEST`; the reason
        is stored and `decided_at` stamped."

        Design: Corner/validations/record_decision_rejected_missing_reason_returns_invalid_request
        """
        workspace = setup_submission_workspace()
        submission = workspace["submission"]
        validate_success(api.submit_registry_submission(submission["id"], REGISTRY))
        resp = api.record_submission_decision(
            submission["id"], {"outcome": "REJECTED"}, REGISTRY)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        current = validate_success(
            api.get_registry_submission(submission["id"], REGISTRY))
        assert current["status"] == "SUBMITTED"

    def test_record_decision_on_accepted_submission_returns_invalid_state(self, api):
        """PRD §3.9: "The clearinghouse's decision is recorded against a
        `SUBMITTED` submission — any other state yields
        `ERR_SUBMISSION_INVALID_STATE`. An `outcome` of `ACCEPTED` stamps
        `decided_at` and closes the submission: `ACCEPTED` is terminal."

        Design: Corner/state_machines/record_decision_on_accepted_submission_returns_invalid_state
        """
        workspace = setup_submission_workspace()
        submission = workspace["submission"]
        validate_success(api.submit_registry_submission(submission["id"], REGISTRY))
        accepted = validate_success(api.record_submission_decision(
            submission["id"], record_decision_payload("ACCEPTED"), REGISTRY))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["decided_at"] is not None
        resp = api.record_submission_decision(
            submission["id"],
            record_decision_payload("REJECTED", rejection_reason="late rejection"),
            REGISTRY)
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_INVALID_STATE,
                       expected_status=409)
        current = validate_success(
            api.get_registry_submission(submission["id"], REGISTRY))
        assert current["status"] == "ACCEPTED"

    def test_revise_draft_submission_returns_invalid_state(self, api):
        """PRD §3.9: "Revising carries a required `correction_note`, moves the
        submission `REJECTED` → `DRAFT` — again, only from `REJECTED`, else
        `ERR_SUBMISSION_INVALID_STATE` — stores the note, and clears `submitted_at`
        and `decided_at` to null, readying the submission for a fresh attempt."

        Design: Corner/state_machines/revise_draft_submission_returns_invalid_state
        """
        workspace = setup_submission_workspace()
        submission = workspace["submission"]
        assert submission["status"] == "DRAFT"
        resp = api.revise_registry_submission(
            submission["id"], revise_payload("premature revise"), REGISTRY)
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_INVALID_STATE,
                       expected_status=409)
        current = validate_success(
            api.get_registry_submission(submission["id"], REGISTRY))
        assert current["status"] == "DRAFT"
