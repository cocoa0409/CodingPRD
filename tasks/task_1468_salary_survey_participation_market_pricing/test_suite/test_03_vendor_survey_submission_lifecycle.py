"""Vendor termination cascade, survey close cascade, submission rework loop,
and survey lifecycle gating (PRD §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_benchmark,
    analyst_headers,
    bootstrap_org,
    create_active_vendor,
    create_draft_submission,
    create_open_survey,
    get_submission,
    get_success_data,
    get_survey,
    get_vendor,
    make_manager_headers,
    move_submission_to_submitted,
    propose_match,
    validate_error,
    validate_success,
)

VENDOR_ADMIN = TEST_USERS["vendor_admin_headers"]


class TestVendorTerminateCascade:
    def test_terminate_cascades_vendor_and_survey_statuses(self, api):
        """PRD §3.3: "Termination moves the vendor to `TERMINATED`, rejects
        every child survey in `DRAFT` or `OPEN`, and — because a rejected
        survey returns its unfinished packages — each of those surveys'
        submission packages in `DRAFT` or `READY` transitions to `RETURNED`
        with `rejection_reason` set to the literal `VENDOR_TERMINATED`".

        Design: Difficulty/transitive_cascade/vendor_terminate_cascade_depth3
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        submission = create_draft_submission(bundle, survey)
        # READY but not yet SUBMITTED — still an "unfinished package".
        get_submission(bundle, submission["id"])
        validate_success(api.mark_submission_ready(submission["id"],
                                                   analyst_headers(bundle)))

        validate_success(api.terminate_vendor(vendor["id"], VENDOR_ADMIN))

        vendor_after = get_vendor(vendor["id"])
        survey_after = get_survey(survey["id"])
        assert vendor_after["status"] == "TERMINATED"
        assert survey_after["status"] == "REJECTED", (
            f"Child OPEN survey must be REJECTED by termination, got "
            f"{survey_after['status']}")

    def test_terminate_cascades_ready_submission_to_returned(self, api):
        """PRD §3.3: "each of those surveys' submission packages in `DRAFT` or
        `READY` transitions to `RETURNED` with `rejection_reason` set to the
        literal `VENDOR_TERMINATED`".

        Design: Difficulty/transitive_cascade/vendor_terminate_cascade_depth3
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        submission = create_draft_submission(bundle, survey)
        validate_success(api.mark_submission_ready(submission["id"],
                                                   analyst_headers(bundle)))

        validate_success(api.terminate_vendor(vendor["id"], VENDOR_ADMIN))

        sub_after = get_submission(bundle, submission["id"])
        assert sub_after["status"] == "RETURNED"
        assert sub_after["rejection_reason"] == "VENDOR_TERMINATED", (
            f"rejection_reason must be the literal VENDOR_TERMINATED, got "
            f"{sub_after['rejection_reason']!r}")


class TestSurveyCloseCascade:
    def test_close_returns_draft_submissions_with_survey_closed_reason(self, api):
        """PRD §3.4: "in both cases the survey moves from `OPEN` to `CLOSED`,
        and every child submission package still in `DRAFT` or `READY` is
        returned with `rejection_reason` set to `SURVEY_CLOSED`."

        Design: Corner/state_machines/survey_close_cascades_draft_submissions_to_returned
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        submission = create_draft_submission(bundle, survey)

        validate_success(api.close_survey(survey["id"], VENDOR_ADMIN))

        sub_after = get_submission(bundle, submission["id"])
        assert sub_after["status"] == "RETURNED"
        assert sub_after["rejection_reason"] == "SURVEY_CLOSED"

    def test_vendor_terminate_with_open_submissions_rejected(self, api):
        """PRD §3.3: "A `VendorAdmin` may instead terminate an `ACTIVE` vendor
        early, but only when no child survey is sitting in `SUBMITTED` status
        — a vendor with submissions in flight cannot be cut off, and the
        attempt fails with `ERR_VENDOR_HAS_OPEN_SUBMISSIONS`."

        Design: Corner/validations/vendor_terminate_with_open_submissions_rejected
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        submission = create_draft_submission(bundle, survey)
        move_submission_to_submitted(bundle, submission["id"])
        closed = validate_success(api.close_survey(survey["id"], VENDOR_ADMIN))
        assert closed["status"] == "SUBMITTED", (
            "Survey with a SUBMITTED package must advance to SUBMITTED on close")

        resp = api.terminate_vendor(vendor["id"], VENDOR_ADMIN)
        validate_error(resp, ApiErrorId.ERR_VENDOR_HAS_OPEN_SUBMISSIONS)


class TestSubmissionReworkLoop:
    def _returned_submission(self, api):
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        submission = create_draft_submission(bundle, survey)
        move_submission_to_submitted(bundle, submission["id"])
        returned = validate_success(api.return_submission(
            submission["id"], {"reason": "incomplete_geo"}, VENDOR_ADMIN))
        assert returned["status"] == "RETURNED"
        return bundle, submission

    def test_rework_moves_returned_submission_back_to_draft(self, api):
        """PRD §3.4: "a `RETURNED` package may be reworked: the analyst moves
        it back to `DRAFT`, which requires the parent survey to be `OPEN`
        again and the deadline still open (`ERR_SUBMISSION_WINDOW_CLOSED`)".

        Design: Difficulty/non_linear_state_machine/submission_cyclic_rework_loop
        """
        bundle, submission = self._returned_submission(api)
        reworked = validate_success(api.rework_submission(
            submission["id"], analyst_headers(bundle)))
        assert reworked["status"] == "DRAFT", (
            f"Rework must rewind the package to DRAFT, got {reworked['status']}")

    def test_rework_clears_vendor_feedback_fields(self, api):
        """PRD §3.4: "and which clears `rejection_reason`, `prepared_at`, and
        `submitted_at` all back to null so the package can begin its cycle
        anew."

        Design: Difficulty/non_linear_state_machine/submission_cyclic_rework_loop
        """
        bundle, submission = self._returned_submission(api)
        reworked = validate_success(api.rework_submission(
            submission["id"], analyst_headers(bundle)))
        assert reworked["rejection_reason"] is None
        assert reworked["prepared_at"] is None
        assert reworked["submitted_at"] is None


class TestSubmissionSurveyGating:
    def test_mark_ready_succeeds_while_survey_open(self, api):
        """PRD §3.4: "Marking a package ready — the analyst moving it from
        `DRAFT` to `READY` — enforces four checks in ladder order: the parent
        survey must be `OPEN` (`ERR_SURVEY_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/submission_mark_ready_depends_on_survey_open
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        submission = create_draft_submission(bundle, survey)
        ready = validate_success(api.mark_submission_ready(
            submission["id"], analyst_headers(bundle)))
        assert ready["status"] == "READY"
        assert ready["prepared_at"] is not None, (
            "Success stamps prepared_at with the current logical time")

    def test_mark_ready_rejected_when_survey_not_open(self, api):
        """PRD §3.4: "Marking a package ready — the analyst moving it from
        `DRAFT` to `READY` — enforces four checks in ladder order: the parent
        survey must be `OPEN` (`ERR_SURVEY_NOT_OPEN`)".

        The package is DRAFT (so the DRAFT->READY transition itself is legal)
        but the parent survey never opened, so the survey-lifecycle gate fires.

        Design: Difficulty/cross_entity_state_dependency/submission_mark_ready_depends_on_survey_open
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        # Survey left in DRAFT (never opened).
        survey = get_success_data(
            api.create_survey(vendor["id"], {
                "survey_code": "S1", "edition_year": 2026,
                "data_effective_date": "2026-01-01",
                "submission_deadline": "2026-12-31",
                "industry_cut_supported": ["ALL_INDUSTRIES"]}, VENDOR_ADMIN))
        submission = create_draft_submission(bundle, survey)
        resp = api.mark_submission_ready(submission["id"], analyst_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_OPEN)


class TestSubmissionAndMatchBasics:
    def test_submit_on_draft_returns_invalid_state(self, api):
        """PRD §2.6: "generic state-transition legality for the target
        resource, failing as `ERR_INVALID_STATE_TRANSITION`".
        PRD §3.4: "Submitting the ready package — `READY` to `SUBMITTED`".

        Design: Corner/state_machines/survey_submit_on_draft_returns_invalid_state
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        submission = create_draft_submission(bundle, survey)
        resp = api.submit_submission(submission["id"], analyst_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_terminal_survey_accepted_rejects_further_transitions(self, api):
        """PRD §3.4: "Survey acceptance and rejection are terminal".
        PRD §2.6: "generic state-transition legality for the target resource,
        failing as `ERR_INVALID_STATE_TRANSITION`".

        Design: Corner/state_machines/terminal_survey_accepted_rejects_further_transitions
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        submission = create_draft_submission(bundle, survey)
        move_submission_to_submitted(bundle, submission["id"])
        validate_success(api.close_survey(survey["id"], VENDOR_ADMIN))
        accepted = validate_success(api.accept_survey(survey["id"], VENDOR_ADMIN))
        assert accepted["status"] == "ACCEPTED"

        resp = api.reject_survey(survey["id"], {"reason": "late"}, VENDOR_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_match_initial_state_is_proposed(self, api):
        """PRD §3.5: "Matches are born in `PROPOSED`".

        Design: Corner/state_machines/match_initial_state_is_proposed
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        benchmark = add_benchmark(bundle, survey)
        match = propose_match(bundle, survey, bundle["job"], benchmark)
        assert match["status"] == "PROPOSED", (
            f"Newly proposed match must be PROPOSED, got {match['status']}")
        assert match["reviewer_employee_id"] is None, (
            "Until a match is approved, its reviewer_employee_id remains null")
