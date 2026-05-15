"""Interview round scheduling, slot overlap, and feedback (PRD §3.5)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_EPOCH,
    advance_clock_to,
    advance_clock_by,
    assert_interview_round,
    bind_hr_user,
    candidate_confirm_payload,
    candidate_confirm_slot,
    create_candidate,
    create_interview_round,
    create_interview_round_payload,
    create_live_posting,
    create_verified_company,
    forward_application,
    iso_utc,
    make_candidate_headers,
    make_hr_user_headers,
    mark_application_read,
    publish_round_slots,
    publish_slots_payload,
    reset_clock_to_epoch,
    submit_application,
    submit_round_feedback,
    submit_round_feedback_payload,
    validate_error,
    validate_success,
)


def _seed_forwarded_application(api):
    """Helper: VERIFIED Company + LIVE posting + candidate + FORWARDED
    Application. Returns (company, hr_user, candidate, application)."""
    company, hr_user = create_verified_company()
    posting = create_live_posting(company["id"], hr_user["id"])
    candidate = create_candidate(visibility_mode="PUBLIC")
    application = submit_application(candidate["id"], posting["id"])
    mark_application_read(application["id"], hr_user["id"])
    forward_application(application["id"], hr_user["id"])
    return company, hr_user, candidate, application


# ===========================================================================
# Round creation (PRD §3.5, §3.4)
# ===========================================================================
class TestInterviewRoundCreate:

    def test_first_round_advances_application_to_interview(self, api):
        """PRD §3.4: "Creating the first `InterviewRound` for the
        application advances `FORWARDED` to `INTERVIEW`."

        Claim: creating the first round on a FORWARDED application moves
        the application to INTERVIEW.
        """
        company, hr_user, candidate, application = _seed_forwarded_application(api)
        round_row = create_interview_round(application["id"], hr_user["id"])
        assert_interview_round(round_row)
        assert round_row["round_status"] == "DRAFT"
        app = validate_success(
            api.get_application(
                application["id"], make_hr_user_headers(hr_user["id"]),
            ),
            expected_status=200,
        )
        assert app["application_status"] == "INTERVIEW"

    def test_round_index_starts_at_one(self, api):
        """PRD §3.5: "The `round_index` is auto-assigned: the first round
        on the application is index 1, the second index 2, and so on."

        Claim: the first round has round_index==1.
        """
        company, hr_user, candidate, application = _seed_forwarded_application(api)
        round_row = create_interview_round(application["id"], hr_user["id"])
        assert round_row["round_index"] == 1


# ===========================================================================
# Slot publishing (PRD §3.5, validations 13, 14)
# ===========================================================================
class TestPublishSlots:

    def test_publish_with_past_slot_returns_slot_in_past(self, api):
        """PRD §3.5: "every entry in `candidate_time_slot_options` must
        be strictly greater than the current instant; any slot at or
        before now yields `ERR_SLOT_IN_PAST`."

        Claim: a slot at TEST_EPOCH (== now()) yields ERR_SLOT_IN_PAST.
        """
        reset_clock_to_epoch()
        company, hr_user, candidate, application = _seed_forwarded_application(api)
        round_row = create_interview_round(application["id"], hr_user["id"])
        resp = api.publish_slots(
            round_row["id"],
            publish_slots_payload([iso_utc(TEST_EPOCH)]),  # equals now()
            make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_IN_PAST.value)

    def test_publish_with_future_slot_advances_to_awaiting_candidate(self, api):
        """PRD §3.5: "On success the round advances from `DRAFT` to
        `AWAITING_CANDIDATE`."

        Claim: publish-slots with a strictly future slot moves DRAFT →
        AWAITING_CANDIDATE.
        """
        reset_clock_to_epoch()
        company, hr_user, candidate, application = _seed_forwarded_application(api)
        round_row = create_interview_round(application["id"], hr_user["id"])
        slot = TEST_EPOCH + timedelta(hours=2)
        resp = api.publish_slots(
            round_row["id"],
            publish_slots_payload([iso_utc(slot)]),
            make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["round_status"] == "AWAITING_CANDIDATE"


# ===========================================================================
# Slot overlap (PRD §3.5, calc interview_slot_overlap, validation 14)
# ===========================================================================
class TestSlotOverlap:

    def test_candidate_confirm_collides_with_existing_scheduled(self, api):
        """PRD §3.5: "for each interviewer in `interviewer_user_ids`, the
        set of half-open candidate windows (each spanning sixty minutes
        from the proposed start) is compared against every existing
        `SCHEDULED` `InterviewRound` whose interviewers include that user;
        two windows collide if and only if the start of the first is
        strictly less than the end of the second and the start of the
        second is strictly less than the end of the first."

        Claim: a candidate-confirm whose chosen slot overlaps an existing
        SCHEDULED round (sharing a common interviewer) yields
        ERR_INTERVIEWER_BUSY.
        """
        reset_clock_to_epoch()
        # To exercise the candidate-confirm collision check (rather than the
        # publish-time collision check), R2's slots must be published BEFORE
        # R1 transitions to SCHEDULED — otherwise R2.publish would itself
        # fail with ERR_INTERVIEWER_BUSY (PRD §3.5 publish-time check). The
        # confirm-time check fires when R1 confirms first and R2 confirms
        # second.
        company, hr_user_a, candidate_a, app_a = _seed_forwarded_application(api)
        r1 = create_interview_round(app_a["id"], hr_user_a["id"])
        slot1 = TEST_EPOCH + timedelta(hours=1)
        publish_round_slots(r1["id"], hr_user_a["id"], [slot1])
        # Build R2 on a separate application but include hr_user_a in the
        # panel as a shared interviewer.
        company_b, hr_user_b, candidate_b, app_b = _seed_forwarded_application(api)
        r2 = create_interview_round(
            app_b["id"], hr_user_b["id"],
            interviewer_user_ids=[hr_user_b["id"], hr_user_a["id"]],
        )
        slot2 = TEST_EPOCH + timedelta(hours=1, minutes=30)  # overlaps slot1+60min window
        # Publish R2's slot BEFORE R1 is confirmed (no SCHEDULED round yet).
        publish_round_slots(r2["id"], hr_user_b["id"], [slot2])
        # Now confirm R1 → SCHEDULED.
        candidate_confirm_slot(r1["id"], candidate_a["id"], slot1)
        # Candidate B's confirm now collides with R1's SCHEDULED window.
        resp = api.candidate_confirm_slot(
            r2["id"], candidate_confirm_payload(iso_utc(slot2)),
            make_candidate_headers(candidate_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEWER_BUSY.value)

    def test_touching_boundary_is_not_overlap(self, api):
        """PRD §3.5: "Touching exactly at a boundary (the end of one
        round equals the start of the next) is not a collision under
        this half-open rule."

        Claim: a slot starting exactly at the previous round's
        scheduled_end_at does NOT collide.
        """
        reset_clock_to_epoch()
        company, hr_user_a, candidate_a, app_a = _seed_forwarded_application(api)
        r1 = create_interview_round(app_a["id"], hr_user_a["id"])
        slot1 = TEST_EPOCH + timedelta(hours=1)  # ends at T0+2h
        publish_round_slots(r1["id"], hr_user_a["id"], [slot1])
        candidate_confirm_slot(r1["id"], candidate_a["id"], slot1)
        company_b, hr_user_b, candidate_b, app_b = _seed_forwarded_application(api)
        r2 = create_interview_round(
            app_b["id"], hr_user_b["id"],
            interviewer_user_ids=[hr_user_b["id"], hr_user_a["id"]],
        )
        # Slot exactly at end of slot1.
        slot2 = TEST_EPOCH + timedelta(hours=2)
        publish_round_slots(r2["id"], hr_user_b["id"], [slot2])
        resp = api.candidate_confirm_slot(
            r2["id"], candidate_confirm_payload(iso_utc(slot2)),
            make_candidate_headers(candidate_b["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["round_status"] == "SCHEDULED"


# ===========================================================================
# Candidate confirm + scheduled_end_at (PRD §3.5)
# ===========================================================================
class TestCandidateConfirm:

    def test_confirm_advances_to_scheduled_and_sets_end_at(self, api):
        """PRD §3.5: "A successful confirmation advances the round from
        `AWAITING_CANDIDATE` to `SCHEDULED`, sets `scheduled_start_at` to
        the selected slot, sets `scheduled_end_at` to exactly sixty
        minutes later regardless of the round's `mode`."

        Claim: confirm moves AWAITING_CANDIDATE → SCHEDULED and sets
        scheduled_end_at = scheduled_start_at + 60 minutes.
        """
        reset_clock_to_epoch()
        company, hr_user, candidate, application = _seed_forwarded_application(api)
        round_row = create_interview_round(application["id"], hr_user["id"])
        slot = TEST_EPOCH + timedelta(hours=3)
        publish_round_slots(round_row["id"], hr_user["id"], [slot])
        resp = api.candidate_confirm_slot(
            round_row["id"], candidate_confirm_payload(iso_utc(slot)),
            make_candidate_headers(candidate["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["round_status"] == "SCHEDULED"
        # scheduled_start_at and scheduled_end_at should reflect +60 min.
        from datetime import datetime
        # Parse Z-suffix timestamps.
        def _parse(s):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        start = _parse(data["scheduled_start_at"])
        end = _parse(data["scheduled_end_at"])
        assert (end - start) == timedelta(minutes=60), (
            f"scheduled_end_at - scheduled_start_at must be 60 min, "
            f"got {end - start}"
        )

    def test_confirm_with_unlisted_slot_returns_invalid_state_or_validation(self, api):
        """PRD §3.5: "The `selected_slot` must be one of the entries
        previously published in `candidate_time_slot_options`..."

        Claim: confirming with a slot that was never published should
        fail. PRD does not pin one specific error_id for this exact
        sub-case (it lies between schema validation and state-machine
        guards), so we assert the response is an error (not 2xx).
        """
        reset_clock_to_epoch()
        company, hr_user, candidate, application = _seed_forwarded_application(api)
        round_row = create_interview_round(application["id"], hr_user["id"])
        published = TEST_EPOCH + timedelta(hours=2)
        publish_round_slots(round_row["id"], hr_user["id"], [published])
        unlisted = TEST_EPOCH + timedelta(hours=5)
        resp = api.candidate_confirm_slot(
            round_row["id"],
            candidate_confirm_payload(iso_utc(unlisted)),
            make_candidate_headers(candidate["id"]),
        )
        assert resp.status_code >= 400, (
            "Confirming an unlisted slot must not succeed; "
            f"got status {resp.status_code}"
        )


# ===========================================================================
# Auto-transition SCHEDULED → FEEDBACK_PENDING (PRD §3.5)
# ===========================================================================
class TestRoundAutoTransition:

    def test_clock_advance_to_end_at_moves_to_feedback_pending(self, api):
        """PRD §3.5: "Once the current instant is at or after
        `scheduled_end_at`, the clock-advance capability auto-transitions
        the round from `SCHEDULED` to `FEEDBACK_PENDING`."

        Claim: clock-advance to scheduled_end_at moves SCHEDULED → FEEDBACK_PENDING.
        """
        reset_clock_to_epoch()
        company, hr_user, candidate, application = _seed_forwarded_application(api)
        round_row = create_interview_round(application["id"], hr_user["id"])
        slot = TEST_EPOCH + timedelta(hours=1)
        publish_round_slots(round_row["id"], hr_user["id"], [slot])
        round_row = candidate_confirm_slot(
            round_row["id"], candidate["id"], slot,
        )
        advance_clock_to(slot + timedelta(minutes=60))
        data = validate_success(
            api.get_interview_round(
                round_row["id"], make_hr_user_headers(hr_user["id"]),
            ),
            expected_status=200,
        )
        assert data["round_status"] == "FEEDBACK_PENDING"


# ===========================================================================
# Feedback (PRD §3.5)
# ===========================================================================
class TestFeedback:

    def test_pass_decision_advances_to_passed(self, api):
        """PRD §3.5: "A `PASS` decision advances the round to `PASSED`
        and persists `feedback_decision` accordingly."

        Claim: feedback_decision=PASS moves FEEDBACK_PENDING → PASSED.
        """
        reset_clock_to_epoch()
        company, hr_user, candidate, application = _seed_forwarded_application(api)
        round_row = create_interview_round(application["id"], hr_user["id"])
        slot = TEST_EPOCH + timedelta(hours=1)
        publish_round_slots(round_row["id"], hr_user["id"], [slot])
        round_row = candidate_confirm_slot(round_row["id"], candidate["id"], slot)
        advance_clock_to(slot + timedelta(minutes=60))
        resp = api.submit_round_feedback(
            round_row["id"], submit_round_feedback_payload("PASS"),
            make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["round_status"] == "PASSED"
        assert data["feedback_decision"] == "PASS"

    def test_fail_decision_cascades_application_to_rejected(self, api):
        """PRD §3.5: "A `FAIL` decision ... advances the round to
        `FAILED`, persists `feedback_decision`, and cascades — the parent
        `Application` moves to `REJECTED`."

        Claim: feedback_decision=FAIL moves round to FAILED and cascades
        parent Application to REJECTED.
        """
        reset_clock_to_epoch()
        company, hr_user, candidate, application = _seed_forwarded_application(api)
        round_row = create_interview_round(application["id"], hr_user["id"])
        slot = TEST_EPOCH + timedelta(hours=1)
        publish_round_slots(round_row["id"], hr_user["id"], [slot])
        round_row = candidate_confirm_slot(round_row["id"], candidate["id"], slot)
        advance_clock_to(slot + timedelta(minutes=60))
        resp = api.submit_round_feedback(
            round_row["id"], submit_round_feedback_payload("FAIL"),
            make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["round_status"] == "FAILED"
        # Application should cascade to REJECTED.
        app = validate_success(
            api.get_application(
                application["id"], make_hr_user_headers(hr_user["id"]),
            ),
            expected_status=200,
        )
        assert app["application_status"] == "REJECTED"

    def test_invalid_feedback_decision_returns_feedback_invalid(self, api):
        """PRD §2.7: "`ERR_FEEDBACK_INVALID` (422) when `feedback_decision`
        on an interview round is not one of `PASS`, `FAIL`, or `HOLD`."

        Claim: feedback_decision=='SOMETHING_ELSE' yields
        ERR_FEEDBACK_INVALID.
        """
        reset_clock_to_epoch()
        company, hr_user, candidate, application = _seed_forwarded_application(api)
        round_row = create_interview_round(application["id"], hr_user["id"])
        slot = TEST_EPOCH + timedelta(hours=1)
        publish_round_slots(round_row["id"], hr_user["id"], [slot])
        round_row = candidate_confirm_slot(round_row["id"], candidate["id"], slot)
        advance_clock_to(slot + timedelta(minutes=60))
        resp = api.submit_round_feedback(
            round_row["id"], {"feedback_decision": "INVALID_KIND"},
            make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FEEDBACK_INVALID.value)
