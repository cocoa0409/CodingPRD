"""Service referrals, satisfaction surveys, and the pinned rounding order."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_assignment,
    create_program,
    create_service_referral_payload,
    enroll_participant,
    issue_survey,
    log_call,
    return_survey_payload,
    set_clock,
    setup_calling_environment,
    setup_enrolled_participant,
    validate_error,
    validate_success,
)


class TestReferralStates:
    def test_referral_close_from_draft_rejected(self, api, coordinator_headers, reviewer_headers):
        """PRD §3.8: "Withdrawal is allowed from `DRAFT` or `SUBMITTED` and is terminal, as is closure: a `QualityReviewer` closes an `ACCEPTED` referral into `CLOSED`."

        Design: Corner/state_machines/referral_close_from_draft_rejected
        """
        program, participant = setup_enrolled_participant(schedules=())
        referral = validate_success(api.create_service_referral(
            create_service_referral_payload(participant_id=participant["id"],
                                            service_type="TRANSPORT"),
            coordinator_headers,
        ), 201)
        assert referral["status"] == "DRAFT"
        resp = api.close_service_referral(referral["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = validate_success(api.get_service_referral(referral["id"], coordinator_headers))
        assert after["status"] == "DRAFT"


class TestReferralSla:
    def test_referral_sla_overdue_strictly_after_due(self, api, coordinator_headers):
        """PRD §3.8: "Submission stamps `submitted_at` and computes `sla_due_at` as `submitted_at` plus the priority's response window: 24 hours for `URGENT`, 72 for `STANDARD`, or 168 hours — one week — for `ROUTINE`."
        PRD §3.8: "A referral reads as `overdue` exactly while its status is `SUBMITTED` and the logical clock is strictly later than `sla_due_at`; at the precise deadline instant it is not yet overdue."

        Design: Corner/calculations/referral_sla_overdue_strictly_after_due
        """
        program, participant = setup_enrolled_participant(schedules=())
        set_clock("2026-08-03T10:00:00Z")
        referral = validate_success(api.create_service_referral(
            create_service_referral_payload(participant_id=participant["id"],
                                            service_type="HOME_HEALTH", priority="URGENT"),
            coordinator_headers,
        ), 201)
        submitted = validate_success(
            api.submit_service_referral(referral["id"], coordinator_headers)
        )
        assert submitted["sla_due_at"].startswith("2026-08-04T10:00:00"), (
            f"URGENT = submitted_at + 24h, got {submitted['sla_due_at']!r}"
        )
        # At exactly sla_due_at the referral is not yet overdue.
        set_clock("2026-08-04T10:00:00Z")
        at_due = validate_success(api.get_service_referral(referral["id"], coordinator_headers))
        assert at_due["overdue"] is False
        # One second past the deadline it flips.
        set_clock("2026-08-04T10:00:01Z")
        past_due = validate_success(api.get_service_referral(referral["id"], coordinator_headers))
        assert past_due["overdue"] is True


class TestReferralSubmitGatedByFlag:
    def _setup_two_logs(self, api, coordinator_headers):
        program, participant, volunteer = setup_calling_environment()
        a1 = create_assignment(participant["id"], volunteer["id"], "2026-08-03",
                               window_start="09:00", window_end="09:30")
        a2 = create_assignment(participant["id"], volunteer["id"], "2026-08-03",
                               window_start="10:00", window_end="10:30")
        set_clock("2026-08-03T11:00:00Z")
        log_ok = log_call(a1["id"], volunteer["id"], "2026-08-03T09:05:00Z", "REACHED_OK",
                          duration_seconds=300)
        log_flag = log_call(a2["id"], volunteer["id"], "2026-08-03T10:05:00Z",
                            "REACHED_CONCERN", duration_seconds=300,
                            concern_level="ROUTINE", concern_categories=["MEDICATION"])
        return program, participant, volunteer, log_ok, log_flag

    def test_submit_from_unflagged_log_rejected(self, api, coordinator_headers):
        """PRD §3.8: "Submitting the draft requires it to be in `DRAFT` (`ERR_INVALID_STATE` otherwise) and, when `source_call_log_id` is set, requires that log's `concern_flag` to be true — a referral sourced from an unflagged log fails with `ERR_CONCERN_NOT_FLAGGED`."

        Design: Difficulty/cross_entity_state_dependency/referral_submit_gated_by_call_log_flag
        """
        program, participant, volunteer, log_ok, log_flag = self._setup_two_logs(
            api, coordinator_headers
        )
        assert log_ok["concern_flag"] is False
        referral = validate_success(api.create_service_referral(
            create_service_referral_payload(participant_id=participant["id"],
                                            service_type="MEALS",
                                            source_call_log_id=log_ok["id"]),
            coordinator_headers,
        ), 201)
        resp = api.submit_service_referral(referral["id"], coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_CONCERN_NOT_FLAGGED, 422)
        after = validate_success(api.get_service_referral(referral["id"], coordinator_headers))
        assert after["status"] == "DRAFT", "the rejected submit leaves the referral in DRAFT"

    def test_submit_from_flagged_log_stamps_sla(self, api, coordinator_headers):
        """PRD §3.8: "Submission stamps `submitted_at` and computes `sla_due_at` as `submitted_at` plus the priority's response window: 24 hours for `URGENT`, 72 for `STANDARD`, or 168 hours — one week — for `ROUTINE`."
        PRD §3.8: "Submitting the draft requires it to be in `DRAFT` (`ERR_INVALID_STATE` otherwise) and, when `source_call_log_id` is set, requires that log's `concern_flag` to be true — a referral sourced from an unflagged log fails with `ERR_CONCERN_NOT_FLAGGED`."

        Design: Difficulty/cross_entity_state_dependency/referral_submit_gated_by_call_log_flag
        """
        program, participant, volunteer, log_ok, log_flag = self._setup_two_logs(
            api, coordinator_headers
        )
        assert log_flag["concern_flag"] is True, "outcome REACHED_CONCERN flags the log"
        referral = validate_success(api.create_service_referral(
            create_service_referral_payload(participant_id=participant["id"],
                                            service_type="MEALS",
                                            source_call_log_id=log_flag["id"]),
            coordinator_headers,
        ), 201)
        submitted = validate_success(
            api.submit_service_referral(referral["id"], coordinator_headers)
        )
        assert submitted["status"] == "SUBMITTED"
        # STANDARD: submitted at clock 2026-08-03T11:00:00Z + 72h.
        assert submitted["sla_due_at"].startswith("2026-08-06T11:00:00")


class TestReferralReworkLoop:
    def _setup_flagged_log(self, api, coordinator_headers):
        program, participant, volunteer = setup_calling_environment()
        assignment = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        set_clock("2026-08-03T10:00:00Z")
        log = log_call(assignment["id"], volunteer["id"], "2026-08-03T09:05:00Z",
                       "REACHED_CONCERN", duration_seconds=420, concern_level="ROUTINE",
                       concern_categories=["NUTRITION"], follow_up_needed=True)
        return program, participant, log

    def test_decline_then_revise_returns_draft_with_cleared_submission(self, api, coordinator_headers):
        """PRD §3.8: "A declined referral can be reworked — revision returns it `DECLINED` → `DRAFT`, clearing `decline_reason` and clearing both `submitted_at` and `sla_due_at` until it is resubmitted."
        PRD §3.8: "The provider-facing loop continues from `SUBMITTED`: acceptance moves the referral to `ACCEPTED`; a decline moves it to `DECLINED` with the supplied `reason` captured in `decline_reason`."

        Design: Difficulty/non_linear_state_machine/referral_decline_revise_rework_loop
        """
        program, participant, log = self._setup_flagged_log(api, coordinator_headers)
        referral = validate_success(api.create_service_referral(
            create_service_referral_payload(participant_id=participant["id"],
                                            service_type="MEALS", priority="STANDARD",
                                            source_call_log_id=log["id"]),
            coordinator_headers,
        ), 201)
        assert referral["status"] == "DRAFT"
        submitted = validate_success(
            api.submit_service_referral(referral["id"], coordinator_headers)
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["sla_due_at"].startswith("2026-08-06T10:00:00"), (
            "STANDARD 72h from the 2026-08-03T10:00:00Z clock"
        )
        declined = validate_success(api.decline_service_referral(
            referral["id"], {"reason": "provider full"}, coordinator_headers
        ))
        assert declined["status"] == "DECLINED"
        revised = validate_success(api.revise_service_referral(referral["id"], coordinator_headers))
        assert revised["status"] == "DRAFT", "the rework loop leg DECLINED -> DRAFT"
        assert revised.get("submitted_at") is None, "revision clears the submission"
        assert revised.get("sla_due_at") is None
        assert revised.get("decline_reason") is None

    def test_resubmit_recomputes_sla_then_accept_close(self, api, coordinator_headers, reviewer_headers):
        """PRD §3.8: "A declined referral can be reworked — revision returns it `DECLINED` → `DRAFT`, clearing `decline_reason` and clearing both `submitted_at` and `sla_due_at` until it is resubmitted."
        PRD §3.8: "Withdrawal is allowed from `DRAFT` or `SUBMITTED` and is terminal, as is closure: a `QualityReviewer` closes an `ACCEPTED` referral into `CLOSED`."

        Design: Difficulty/non_linear_state_machine/referral_decline_revise_rework_loop
        """
        program, participant, log = self._setup_flagged_log(api, coordinator_headers)
        referral = validate_success(api.create_service_referral(
            create_service_referral_payload(participant_id=participant["id"],
                                            service_type="MEALS", priority="STANDARD",
                                            source_call_log_id=log["id"]),
            coordinator_headers,
        ), 201)
        validate_success(api.submit_service_referral(referral["id"], coordinator_headers))
        validate_success(
            api.decline_service_referral(referral["id"], {"reason": "provider full"},
                                         coordinator_headers)
        )
        validate_success(api.revise_service_referral(referral["id"], coordinator_headers))
        # Resubmit under a new clock: sla_due_at recomputes from it.
        set_clock("2026-08-04T09:00:00Z")
        resubmitted = validate_success(
            api.submit_service_referral(referral["id"], coordinator_headers)
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["sla_due_at"].startswith("2026-08-07T09:00:00"), (
            "recomputed from the new clock, not restored from the first submission"
        )
        accepted = validate_success(
            api.accept_service_referral(referral["id"], coordinator_headers)
        )
        assert accepted["status"] == "ACCEPTED"
        closed = validate_success(api.close_service_referral(referral["id"], reviewer_headers))
        assert closed["status"] == "CLOSED", (
            "full cycle DRAFT -> SUBMITTED -> DECLINED -> DRAFT -> SUBMITTED -> ACCEPTED -> CLOSED"
        )


class TestSurveyDuplicateAndShape:
    def test_duplicate_survey_period_rejected(self, api, intake_headers):
        """PRD §3.9: "An `IntakeWorker` issues a survey to an enrolled participant for a `period_month` (a `YYYY-MM` string); at most one survey exists per participant per period, a duplicate failing with `ERR_SURVEY_PERIOD_DUPLICATE`."

        Design: Corner/validations/duplicate_survey_period_rejected
        """
        program, participant = setup_enrolled_participant(schedules=())
        first = issue_survey(participant["id"], "2026-08")
        assert first["status"] == "ISSUED"
        resp = api.issue_satisfaction_survey(
            participant["id"], {"period_month": "2026-08"}, intake_headers
        )
        validate_error(resp, ApiErrorId.ERR_SURVEY_PERIOD_DUPLICATE, 409)
        other = validate_success(
            api.issue_satisfaction_survey(participant["id"], {"period_month": "2026-09"},
                                          intake_headers),
            201,
        )
        assert other["period_month"] == "2026-09", "a distinct period is accepted"

    def test_survey_return_wrong_item_shape_rejected(self, api, intake_headers):
        """PRD §3.9: "Returning the survey records `items`: exactly five integers, each from 1 to 5, in the fixed order companionship, mood, safety, usefulness, overall."
        PRD §2.6: "Independently of this ordering, a malformed payload — a missing required field, an unknown field, an invalid enum value, a `window_start` that is not before its `window_end`, or an out-of-range value — is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/survey_return_wrong_item_shape_rejected
        """
        program, participant = setup_enrolled_participant(schedules=())
        survey = issue_survey(participant["id"], "2026-08")
        err1 = api.return_satisfaction_survey(
            survey["id"], {"items": [4, 3, 5, 2]}, intake_headers
        )
        validate_error(err1, ApiErrorId.ERR_INVALID_REQUEST, 400)
        err2 = api.return_satisfaction_survey(
            survey["id"], {"items": [4, 3, 5, 2, 6]}, intake_headers
        )
        validate_error(err2, ApiErrorId.ERR_INVALID_REQUEST, 400)
        after = validate_success(api.get_satisfaction_survey(survey["id"], intake_headers))
        assert after["status"] == "ISSUED", "no partial mutation after the rejections"
        assert after.get("survey_mean") is None

    def test_survey_return_after_expiry_rejected(self, api, intake_headers, coordinator_headers):
        """PRD §3.9: "The survey is `ISSUED` with `issued_at` at the clock, and remains returnable for the program's `survey_valid_days` (thirty days by default) — the closeout moves one strictly past that boundary to `EXPIRED`."
        PRD §3.9: "The return moves the survey to `SCORED` and computes `survey_mean` as the weighted sum of the five items with weights one, two, one, one, and two respectively, divided by seven, rounded half-up to two decimal places."

        Design: Corner/state_machines/survey_return_after_expiry_rejected
        """
        program, participant = setup_enrolled_participant(schedules=())
        survey = issue_survey(participant["id"], "2026-08")
        # Issued at 2026-08-01T00:00:00Z; 30 days later is 2026-08-31T00:00:00Z.
        set_clock("2026-09-01T00:00:01Z")
        closeout = validate_success(api.daily_closeout(program["id"], coordinator_headers))
        assert survey["id"] in closeout["expired_survey_ids"]
        resp = api.return_satisfaction_survey(
            survey["id"], return_survey_payload(items=[5, 5, 5, 5, 5]), intake_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = validate_success(api.get_satisfaction_survey(survey["id"], intake_headers))
        assert after["status"] == "EXPIRED"
        assert after.get("survey_mean") is None


class TestSatisfactionPinnedRounding:
    def _setup_two_scored_surveys(self, api, intake_headers, reviewer_headers):
        program = create_program(total_capacity=5, max_reserve_slots=0)
        sa = enroll_participant({"full_name": "SA"})
        sb = enroll_participant({"full_name": "SB"})
        survey_a = issue_survey(sa["id"], "2026-08")
        survey_b = issue_survey(sb["id"], "2026-08")
        return program, survey_a, survey_b

    def test_survey_mean_rounded_per_survey(self, api, intake_headers):
        """PRD §3.9: "The return moves the survey to `SCORED` and computes `survey_mean` as the weighted sum of the five items with weights one, two, one, one, and two respectively, divided by seven, rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/satisfaction_per_survey_then_aggregate_rounding
        """
        program, survey_a, survey_b = self._setup_two_scored_surveys(api, intake_headers, None)
        scored_a = validate_success(api.return_satisfaction_survey(
            survey_a["id"], {"items": [5, 4, 3, 4, 5]}, intake_headers
        ))
        assert scored_a["status"] == "SCORED"
        # (1*5 + 2*4 + 1*3 + 1*4 + 2*5) / 7 = 30/7 = 4.2857... -> 4.29
        assert scored_a["survey_mean"] == pytest.approx(4.29, abs=0.005)
        scored_b = validate_success(api.return_satisfaction_survey(
            survey_b["id"], {"items": [1, 1, 1, 1, 1]}, intake_headers
        ))
        assert scored_b["survey_mean"] == pytest.approx(1.00, abs=0.005)

    def test_satisfaction_index_uses_pinned_per_survey_order(self, api, intake_headers, reviewer_headers):
        """PRD §3.9: "The rounding order is pinned — each survey's mean is rounded to two decimals before the aggregation, and the alternative of pooling raw weighted item scores across surveys and dividing once is explicitly not used: the surveys [5,4,3,4,5] and [1,1,1,1,1] yield an index of 2.65 under the pinned order, where pooling would yield 2.64."
        PRD §3.9: "The report's `satisfaction_index` is the mean of `survey_mean` over the program's `SCORED` surveys for the period, rounded half-up to two decimal places, and null when no scored surveys exist."

        Design: Difficulty/combinatorial_formula/satisfaction_per_survey_then_aggregate_rounding
        """
        program, survey_a, survey_b = self._setup_two_scored_surveys(api, intake_headers, reviewer_headers)
        validate_success(api.return_satisfaction_survey(
            survey_a["id"], {"items": [5, 4, 3, 4, 5]}, intake_headers
        ))
        validate_success(api.return_satisfaction_survey(
            survey_b["id"], {"items": [1, 1, 1, 1, 1]}, intake_headers
        ))
        report = validate_success(
            api.generate_outcome_report(program["id"], {"period_month": "2026-08"},
                                        reviewer_headers),
            201,
        )
        # round_half_up((4.29 + 1.00) / 2, 2) = round_half_up(2.645, 2) = 2.65.
        assert report["satisfaction_index"] == pytest.approx(2.65, abs=0.005), (
            "the pinned per-survey-first order yields 2.65; the rejected pooled "
            "order would yield 2.64"
        )
