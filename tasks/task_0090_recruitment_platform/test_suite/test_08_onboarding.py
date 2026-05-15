"""Onboarding lifecycle: checks, no-show, probation conversion (PRD §3.7)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    EARLY_PASS_DECISION_DAYS,
    PROBATION_DAYS,
    TEST_EPOCH,
    advance_clock_to,
    assert_onboarding,
    confirm_onboarded,
    conversion_decision_payload,
    create_onboarding,
    create_onboarding_payload,
    iso_utc,
    make_hr_user_headers,
    onboarding_feedback_payload,
    record_check_payload,
    record_onboarding_check,
    reset_clock_to_epoch,
    setup_accepted_offer,
    setup_onboarded,
    start_onboarding_checks,
    validate_error,
    validate_success,
)


# ===========================================================================
# Onboarding creation (PRD §3.7)
# ===========================================================================
class TestOnboardingCreate:

    def test_create_onboarding_starts_scheduled(self, api):
        """PRD §3.7: "The onboarding starts with `onboarding_status` equal
        to `SCHEDULED`, with `background_check_status` and
        `medical_check_status` both `PENDING`."

        Claim: a new Onboarding is SCHEDULED with PENDING checks.
        """
        bag = setup_accepted_offer()
        start_dt = TEST_EPOCH + timedelta(days=14)
        onboarding = create_onboarding(
            bag["offer"]["id"], bag["hr_user"]["id"],
            start_date=iso_utc(start_dt),
        )
        assert_onboarding(onboarding)
        assert onboarding["onboarding_status"] == "SCHEDULED"
        assert onboarding["background_check_status"] == "PENDING"
        assert onboarding["medical_check_status"] == "PENDING"

    def test_second_onboarding_for_same_offer_rejected(self, api):
        """PRD §3.7 / §2.7: "Onboarding uniqueness — at most one
        `Onboarding` may exist per `Offer`; a second creation yields
        `ERR_ONBOARDING_ALREADY_EXISTS`."

        Claim: creating a second Onboarding for the same Offer yields
        ERR_ONBOARDING_ALREADY_EXISTS.
        """
        bag = setup_accepted_offer()
        start_dt = iso_utc(TEST_EPOCH + timedelta(days=14))
        create_onboarding(
            bag["offer"]["id"], bag["hr_user"]["id"], start_date=start_dt,
        )
        resp = api.create_onboarding(
            create_onboarding_payload(
                offer_id=bag["offer"]["id"], start_date=start_dt,
            ),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ONBOARDING_ALREADY_EXISTS.value)


# ===========================================================================
# Checks lifecycle (PRD §3.7)
# ===========================================================================
class TestCheckLifecycle:

    def test_start_checks_advances_to_checks_running(self, api):
        """PRD §3.7: "Initiating the checks advances `SCHEDULED` to
        `CHECKS_RUNNING`..."

        Claim: start-checks moves SCHEDULED → CHECKS_RUNNING.
        """
        bag = setup_accepted_offer()
        onboarding = create_onboarding(
            bag["offer"]["id"], bag["hr_user"]["id"],
            start_date=iso_utc(TEST_EPOCH + timedelta(days=14)),
        )
        resp = api.start_checks(
            onboarding["id"], make_hr_user_headers(bag["hr_user"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["onboarding_status"] == "CHECKS_RUNNING"

    def test_both_checks_pass_advances_to_ready(self, api):
        """PRD §3.7: "Once `background_check_status` is in `PASSED` or
        `WAIVED` and `medical_check_status` is likewise in `PASSED` or
        `WAIVED`, the platform advances the onboarding from
        `CHECKS_RUNNING` to `READY` on the next record-check call that
        produces this state."

        Claim: after recording BACKGROUND=PASSED and MEDICAL=PASSED,
        onboarding_status becomes READY.
        """
        bag = setup_accepted_offer()
        onboarding = create_onboarding(
            bag["offer"]["id"], bag["hr_user"]["id"],
            start_date=iso_utc(TEST_EPOCH + timedelta(days=14)),
        )
        start_onboarding_checks(onboarding["id"], bag["hr_user"]["id"])
        record_onboarding_check(
            onboarding["id"], bag["hr_user"]["id"], "BACKGROUND", "PASSED",
        )
        result = record_onboarding_check(
            onboarding["id"], bag["hr_user"]["id"], "MEDICAL", "PASSED",
        )
        assert result["onboarding_status"] == "READY"
        assert result["background_check_status"] == "PASSED"
        assert result["medical_check_status"] == "PASSED"

    def test_waived_combination_also_advances_to_ready(self, api):
        """PRD §3.7: "Once `background_check_status` is in `PASSED` or
        `WAIVED` and `medical_check_status` is likewise in `PASSED` or
        `WAIVED`, the platform advances the onboarding from
        `CHECKS_RUNNING` to `READY`..."

        Claim: BACKGROUND=WAIVED + MEDICAL=PASSED also advances to READY.
        """
        bag = setup_accepted_offer()
        onboarding = create_onboarding(
            bag["offer"]["id"], bag["hr_user"]["id"],
            start_date=iso_utc(TEST_EPOCH + timedelta(days=14)),
        )
        start_onboarding_checks(onboarding["id"], bag["hr_user"]["id"])
        record_onboarding_check(
            onboarding["id"], bag["hr_user"]["id"], "BACKGROUND", "WAIVED",
        )
        result = record_onboarding_check(
            onboarding["id"], bag["hr_user"]["id"], "MEDICAL", "PASSED",
        )
        assert result["onboarding_status"] == "READY"

    def test_unknown_check_kind_returns_check_invalid(self, api):
        """PRD §3.7: "An unknown `check_kind` or `outcome` yields
        `ERR_CHECK_INVALID`."

        Claim: check_kind not in {BACKGROUND, MEDICAL} yields
        ERR_CHECK_INVALID.
        """
        bag = setup_accepted_offer()
        onboarding = create_onboarding(
            bag["offer"]["id"], bag["hr_user"]["id"],
            start_date=iso_utc(TEST_EPOCH + timedelta(days=14)),
        )
        start_onboarding_checks(onboarding["id"], bag["hr_user"]["id"])
        resp = api.record_check(
            onboarding["id"],
            record_check_payload(check_kind="DRUG_TEST", outcome="PASSED"),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHECK_INVALID.value)

    def test_unknown_outcome_returns_check_invalid(self, api):
        """PRD §3.7: "An unknown `check_kind` or `outcome` yields
        `ERR_CHECK_INVALID`."

        Claim: outcome not in {PENDING, PASSED, FAILED, WAIVED} yields
        ERR_CHECK_INVALID.
        """
        bag = setup_accepted_offer()
        onboarding = create_onboarding(
            bag["offer"]["id"], bag["hr_user"]["id"],
            start_date=iso_utc(TEST_EPOCH + timedelta(days=14)),
        )
        start_onboarding_checks(onboarding["id"], bag["hr_user"]["id"])
        resp = api.record_check(
            onboarding["id"],
            record_check_payload(check_kind="BACKGROUND", outcome="UNKNOWN"),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHECK_INVALID.value)


# ===========================================================================
# Confirm onboarded (PRD §3.7)
# ===========================================================================
class TestConfirmOnboarded:

    def test_confirm_onboarded_before_start_date_returns_invalid_state(self, api):
        """PRD §3.7: "The HR user then confirms onboarding through the
        confirm-onboarded capability, transitioning `READY` to `ONBOARDED`
        on or after `start_date` (i.e. the current instant must be at or
        after `start_date`)."

        Claim: confirm-onboarded before start_date yields ERR_INVALID_STATE.
        """
        reset_clock_to_epoch()
        bag = setup_accepted_offer()
        start_dt = TEST_EPOCH + timedelta(days=14)
        onboarding = create_onboarding(
            bag["offer"]["id"], bag["hr_user"]["id"],
            start_date=iso_utc(start_dt),
        )
        start_onboarding_checks(onboarding["id"], bag["hr_user"]["id"])
        record_onboarding_check(
            onboarding["id"], bag["hr_user"]["id"], "BACKGROUND", "PASSED",
        )
        record_onboarding_check(
            onboarding["id"], bag["hr_user"]["id"], "MEDICAL", "PASSED",
        )
        # Clock is still at TEST_EPOCH, before start_date.
        resp = api.confirm_onboarded(
            onboarding["id"], make_hr_user_headers(bag["hr_user"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_confirm_onboarded_sets_probation_end_at(self, api):
        """PRD §3.7: "On the `ONBOARDED` transition, `probation_end_at` is
        set to ninety days after `start_date`..."

        Claim: probation_end_at = start_date + 90 days.
        """
        reset_clock_to_epoch()
        bag = setup_accepted_offer()
        start_dt = TEST_EPOCH + timedelta(days=14)
        onboarding = create_onboarding(
            bag["offer"]["id"], bag["hr_user"]["id"],
            start_date=iso_utc(start_dt),
        )
        start_onboarding_checks(onboarding["id"], bag["hr_user"]["id"])
        record_onboarding_check(
            onboarding["id"], bag["hr_user"]["id"], "BACKGROUND", "PASSED",
        )
        record_onboarding_check(
            onboarding["id"], bag["hr_user"]["id"], "MEDICAL", "PASSED",
        )
        advance_clock_to(start_dt)
        result = confirm_onboarded(onboarding["id"], bag["hr_user"]["id"])
        assert result["onboarding_status"] == "ONBOARDED"
        # probation_end_at = start_date + 90 days
        expected = start_dt + timedelta(days=PROBATION_DAYS)
        actual = datetime.fromisoformat(
            result["probation_end_at"].replace("Z", "+00:00"),
        )
        assert actual == expected, (
            f"probation_end_at expected {expected}, got {actual}"
        )


# ===========================================================================
# No-show path (PRD §3.7)
# ===========================================================================
class TestNoShow:

    def test_record_no_show_from_ready_cascades_offer_to_rescinded(self, api):
        """PRD §3.7: "From `READY`, the same capability also transitions
        to `NO_SHOW` once the current instant is at or after `start_date`;
        the parent `Offer` cascades to `RESCINDED` with `rescission_reason`
        `OTHER`."

        Claim: record-no-show from READY moves Onboarding → NO_SHOW and
        cascades Offer → RESCINDED with rescission_reason OTHER.
        """
        reset_clock_to_epoch()
        bag = setup_accepted_offer()
        start_dt = TEST_EPOCH + timedelta(days=14)
        onboarding = create_onboarding(
            bag["offer"]["id"], bag["hr_user"]["id"],
            start_date=iso_utc(start_dt),
        )
        start_onboarding_checks(onboarding["id"], bag["hr_user"]["id"])
        record_onboarding_check(
            onboarding["id"], bag["hr_user"]["id"], "BACKGROUND", "PASSED",
        )
        record_onboarding_check(
            onboarding["id"], bag["hr_user"]["id"], "MEDICAL", "PASSED",
        )
        advance_clock_to(start_dt)
        resp = api.record_no_show(
            onboarding["id"], make_hr_user_headers(bag["hr_user"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["onboarding_status"] == "NO_SHOW"
        offer = validate_success(
            api.get_offer(
                bag["offer"]["id"],
                make_hr_user_headers(bag["hr_user"]["id"]),
            ),
            expected_status=200,
        )
        assert offer["offer_status"] == "RESCINDED"
        assert offer["rescission_reason"] == "OTHER"


# ===========================================================================
# Probation conversion (PRD §3.7)
# ===========================================================================
class TestProbationConversion:

    def test_pass_within_window_advances_to_probation_passed(self, api):
        """PRD §3.7: "A `PASS` decision is allowed up to thirty days
        before `probation_end_at` (so the current instant must be at or
        after `probation_end_at` minus thirty days), advancing the
        onboarding to `PROBATION_PASSED`..."

        Claim: PASS at probation_end_at - 30 days moves ONBOARDED →
        PROBATION_PASSED.
        """
        reset_clock_to_epoch()
        bag = setup_onboarded()
        onboarding = bag["onboarding"]
        probation_end = datetime.fromisoformat(
            onboarding["probation_end_at"].replace("Z", "+00:00"),
        )
        # Advance to exactly probation_end - 30 days (boundary inclusive).
        advance_clock_to(probation_end - timedelta(days=EARLY_PASS_DECISION_DAYS))
        resp = api.conversion_decision(
            onboarding["id"],
            conversion_decision_payload("PASS"),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["onboarding_status"] == "PROBATION_PASSED"

    def test_fail_advances_to_probation_failed(self, api):
        """PRD §3.7: "A `FAIL` decision advances the onboarding to
        `PROBATION_FAILED`..."

        Claim: FAIL moves ONBOARDED → PROBATION_FAILED.
        """
        reset_clock_to_epoch()
        bag = setup_onboarded()
        onboarding = bag["onboarding"]
        probation_end = datetime.fromisoformat(
            onboarding["probation_end_at"].replace("Z", "+00:00"),
        )
        advance_clock_to(probation_end)
        resp = api.conversion_decision(
            onboarding["id"],
            conversion_decision_payload("FAIL"),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["onboarding_status"] == "PROBATION_FAILED"


# ===========================================================================
# Onboarding feedback (PRD §3.7)
# ===========================================================================
class TestOnboardingFeedback:

    def test_candidate_feedback_recorded(self, api):
        """PRD §3.7: "The feedback capability accepts a `side` (`CANDIDATE`
        or `EMPLOYER`) and a `score` (an integer 1 through 5) and records
        `candidate_feedback_score` or `employer_feedback_score` accordingly."

        Claim: feedback with side=CANDIDATE records candidate_feedback_score.
        """
        bag = setup_onboarded()
        onboarding = bag["onboarding"]
        resp = api.submit_onboarding_feedback(
            onboarding["id"],
            onboarding_feedback_payload(side="CANDIDATE", score=4),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["candidate_feedback_score"] == 4

    def test_employer_feedback_recorded(self, api):
        """PRD §3.7: "records `candidate_feedback_score` or
        `employer_feedback_score` accordingly."

        Claim: feedback with side=EMPLOYER records employer_feedback_score.
        """
        bag = setup_onboarded()
        onboarding = bag["onboarding"]
        resp = api.submit_onboarding_feedback(
            onboarding["id"],
            onboarding_feedback_payload(side="EMPLOYER", score=5),
            make_hr_user_headers(bag["hr_user"]["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["employer_feedback_score"] == 5
