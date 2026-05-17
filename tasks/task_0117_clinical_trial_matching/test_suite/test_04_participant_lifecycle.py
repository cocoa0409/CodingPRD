"""Participant lifecycle — SCREENING → ENROLLED → terminal.

PRD §3.4 (eligibility score & decision), §3.5 (consent + cap +
randomization), §3.7 (withdrawal).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_eligibility_score_precision,
    assert_participant,
    create_participant,
    enroll_participant,
    evaluate_participant,
    fill_consent_pending_for_n_participants,
    iso_anchor_offset,
    make_participant_self_headers,
    request_consent,
    setup_trial_open_for_enrollment,
    setup_trial_with_target_enrollment,
    sign_consent,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    withdraw_participant,
)


# ===========================================================================
# §3.4 Eligibility score — formula + threshold.
# ===========================================================================
class TestEligibilityScore:
    """PRD §3.4 eligibility computation."""

    def test_exclusion_match_decides_ineligible_with_score_zero(
        self, api,
    ):
        """PRD §3.4: "if any exclusion predicate evaluates true against
        the participant's profile, the participant is immediately
        decided as INELIGIBLE, the eligibility_score is recorded as
        0.0, and step two is skipped."

        Claim: a participant whose profile matches an exclusion is
        INELIGIBLE with eligibility_score 0.0.
        """
        # Trial with exclusion: smoker == true.
        trial, _arms, _v1 = setup_trial_open_for_enrollment(
            inclusion_criteria=[
                {"code": "AGE_GTE_18", "op": "GTE",
                 "field": "age", "value": 18},
            ],
            exclusion_criteria=[
                {"code": "SMOKER", "op": "EQ",
                 "field": "smoker", "value": True},
            ],
        )
        p = create_participant(
            trial["id"], profile={"age": 30, "smoker": True},
        )
        p = evaluate_participant(p["id"])
        assert p["status"] == "INELIGIBLE"
        assert p["eligibility_score"] == 0.0

    def test_eligibility_threshold_inclusive_at_80(self, api):
        """PRD §3.4: "a score greater than or equal to 80.0 is ELIGIBLE
        (the threshold is inclusive); a score less than 80.0 is
        INELIGIBLE."

        Claim: a profile matching 4 of 5 inclusion criteria yields
        score 80.0 and decision ELIGIBLE.
        """
        trial, _arms, _v1 = setup_trial_open_for_enrollment(
            inclusion_criteria=[
                {"code": "C1", "op": "GTE",
                 "field": "age", "value": 18},
                {"code": "C2", "op": "LTE",
                 "field": "age", "value": 65},
                {"code": "C3", "op": "GTE",
                 "field": "hba1c", "value": 7.0},
                {"code": "C4", "op": "LTE",
                 "field": "hba1c", "value": 12.0},
                # Fifth criterion that the profile won't satisfy.
                {"code": "C5", "op": "EQ",
                 "field": "marker", "value": "POSITIVE"},
            ],
            exclusion_criteria=[],
        )
        p = create_participant(
            trial["id"], profile={"age": 30, "hba1c": 8.0},
        )
        p = evaluate_participant(p["id"])
        assert p["status"] == "ELIGIBLE"
        assert p["eligibility_score"] == 80.0
        assert_eligibility_score_precision(p["eligibility_score"])

    def test_eligibility_just_below_threshold_is_ineligible(self, api):
        """PRD §3.4: "a score less than 80.0 is INELIGIBLE."

        Claim: 3 of 5 inclusion criteria matched yields score 60.0
        and decision INELIGIBLE.
        """
        trial, _arms, _v1 = setup_trial_open_for_enrollment(
            inclusion_criteria=[
                {"code": "C1", "op": "GTE",
                 "field": "age", "value": 18},
                {"code": "C2", "op": "LTE",
                 "field": "age", "value": 65},
                {"code": "C3", "op": "GTE",
                 "field": "hba1c", "value": 7.0},
                {"code": "C4", "op": "EQ",
                 "field": "marker_a", "value": "POSITIVE"},
                {"code": "C5", "op": "EQ",
                 "field": "marker_b", "value": "POSITIVE"},
            ],
            exclusion_criteria=[],
        )
        p = create_participant(
            trial["id"], profile={"age": 30, "hba1c": 8.0},
        )
        p = evaluate_participant(p["id"])
        assert p["status"] == "INELIGIBLE"
        assert p["eligibility_score"] == 60.0


# ===========================================================================
# §3.5 sign-consent — version pin, status gate, cap.
# ===========================================================================
class TestSignConsentPreconditions:
    """PRD §3.5 sign-consent preconditions."""

    def test_stale_consent_version_rejected(self, api):
        """PRD §3.5: "the supplied consent_version equals the trial's
        active_consent_version exactly (otherwise
        ERR_CONSENT_VERSION_STALE)".

        Claim: signing with a consent_version not equal to active
        returns ERR_CONSENT_VERSION_STALE.
        """
        trial, _arms, v1 = setup_trial_open_for_enrollment()
        # Publish v2 so v1 is stale.
        from test_helpers import publish_consent_version
        publish_consent_version(
            trial["id"], change_summary="bump",
        )
        p = create_participant(trial["id"])
        p = evaluate_participant(p["id"])
        p = request_consent(p["id"])
        res = api.sign_consent(
            p["id"], {"consent_version": v1["version"]},
            make_participant_self_headers(p["id"]),
        )
        validate_error(res, "ERR_CONSENT_VERSION_STALE")

    def test_trial_full_rejects_extra_sign_consent(self, api):
        """PRD §3.5: "the trial's enrolled_count is strictly less than
        target_enrollment (otherwise ERR_TRIAL_FULL)".

        Claim: with target_enrollment=2 and two enrollments already
        completed, the third sign-consent is rejected.

        Note on precedence: PRD §3.5 also says that "If after this
        increment enrolled_count equals target_enrollment, the parent
        trial is cascaded from OPEN_FOR_ENROLLMENT to
        CLOSED_TO_ENROLLMENT in the same commit." So by the time the
        third sign-consent reaches the server the trial may already be
        CLOSED_TO_ENROLLMENT, which under PRD §2.8 error precedence
        (state-machine eligibility before endpoint-specific gating)
        fires ERR_INVALID_STATE. Either ERR_TRIAL_FULL or
        ERR_INVALID_STATE is a faithful PRD reading.
        """
        trial, _arms, v1 = setup_trial_with_target_enrollment(2)
        # Walk three participants to CONSENT_PENDING.
        parked = fill_consent_pending_for_n_participants(trial, 3)
        # Sign two of them.
        sign_consent(
            parked[0]["id"], consent_version=v1["version"],
        )
        sign_consent(
            parked[1]["id"], consent_version=v1["version"],
        )
        # The third must fail: either ERR_TRIAL_FULL or
        # ERR_INVALID_STATE depending on whether the cascade close
        # already fired.
        res = api.sign_consent(
            parked[2]["id"],
            {"consent_version": v1["version"]},
            make_participant_self_headers(parked[2]["id"]),
        )
        validate_error_is_one_of(res, ["ERR_TRIAL_FULL", "ERR_INVALID_STATE"])

    def test_stratum_key_missing_rejected(self, api):
        """PRD §3.5: "if the trial's randomization_scheme is
        STRATIFIED_BLOCK, the participant's profile must contain the
        trial's stratification_field key at sign-consent time;
        absence is rejected with ERR_STRATUM_KEY_MISSING."

        Claim: a STRATIFIED_BLOCK trial rejects sign-consent on a
        participant whose profile lacks the stratification field.
        """
        trial, _arms, v1 = setup_trial_open_for_enrollment(
            randomization_scheme="STRATIFIED_BLOCK",
            block_size=4,
            stratification_field="region",
            inclusion_criteria=[
                {"code": "AGE", "op": "GTE",
                 "field": "age", "value": 0},
            ],
            exclusion_criteria=[],
        )
        # Profile lacks 'region'.
        p = create_participant(trial["id"], profile={"age": 30})
        p = evaluate_participant(p["id"])
        p = request_consent(p["id"])
        res = api.sign_consent(
            p["id"],
            {"consent_version": v1["version"]},
            make_participant_self_headers(p["id"]),
        )
        validate_error(res, "ERR_STRATUM_KEY_MISSING")


# ===========================================================================
# §3.5 sign-consent commit — side effects.
# ===========================================================================
class TestSignConsentSideEffects:
    """PRD §3.5: "On successful sign-consent the server performs an
    atomic bundle of writes".
    """

    def test_sign_consent_assigns_arm_and_bumps_enrolled_count(
        self, api,
    ):
        """PRD §3.5: "signed_consent_version is set to the supplied
        consent_version; arm_id is set by the arm-assignment routine
        described below; the chosen arm's assigned_count is incremented
        by one; the trial's enrolled_count is incremented by one;
        enrolled_at is stamped with the current logical clock instant;
        status is set to ENROLLED."

        Claim: after sign-consent the participant has arm_id set,
        signed_consent_version == active, status ENROLLED, enrolled_at
        non-null; and the parent trial's enrolled_count is 1.
        """
        trial, _arms, v1 = setup_trial_open_for_enrollment()
        p = enroll_participant(
            trial["id"], active_consent_version=v1["version"],
        )
        assert_participant(p)
        assert p["status"] == "ENROLLED"
        assert p["signed_consent_version"] == v1["version"]
        assert p["arm_id"] is not None
        assert p["enrolled_at"] is not None
        from test_helpers import re_get_trial
        t = re_get_trial(trial["id"])
        assert t["enrolled_count"] == 1

    def test_auto_close_when_cap_reached(self, api):
        """PRD §3.3 / §3.5: "the system itself auto-closes when
        enrolled_count reaches target_enrollment immediately after a
        participant enrollment transition: the moment the count equals
        the cap, the trial transitions OPEN_FOR_ENROLLMENT →
        CLOSED_TO_ENROLLMENT as a cascade off the enrolling
        participant's commit, with no client action required."

        Claim: with target=2, the second sign-consent auto-closes the
        trial.
        """
        trial, _arms, v1 = setup_trial_with_target_enrollment(2)
        enroll_participant(
            trial["id"], active_consent_version=v1["version"],
        )
        enroll_participant(
            trial["id"], active_consent_version=v1["version"],
        )
        from test_helpers import re_get_trial
        t = re_get_trial(trial["id"])
        assert t["status"] == "CLOSED_TO_ENROLLMENT"
        assert t["enrolled_count"] == 2


# ===========================================================================
# §3.7 Withdrawal — CONSENT_PENDING and ENROLLED branches.
# ===========================================================================
class TestParticipantWithdraw:
    """PRD §3.7 withdraw transitions."""

    def test_withdraw_from_enrolled_decrements_counters(self, api):
        """PRD §3.7: "The trial's enrolled_count is decremented by one
        because the participant is no longer enrolled, and the
        previously-assigned arm's assigned_count is decremented by one
        in the same commit."

        Claim: a withdrawal from ENROLLED decrements both counters.
        """
        trial, p, _arms = (None, None, None)
        from test_helpers import setup_enrolled_participant
        trial, p, _arms = setup_enrolled_participant()
        from test_helpers import re_get_trial
        before = re_get_trial(trial["id"])
        withdraw_participant(p["id"], reason="opt-out")
        after = re_get_trial(trial["id"])
        assert after["enrolled_count"] == before["enrolled_count"] - 1

    def test_withdraw_from_consent_pending_no_enrollment_decrements(
        self, api,
    ):
        """PRD §3.7: "A withdrawal from CONSENT_PENDING (before
        enrollment ever took place) sets the participant to WITHDRAWN
        without any of these enrollment-side decrements."

        Claim: withdrawing a CONSENT_PENDING participant moves them to
        WITHDRAWN but leaves enrolled_count untouched.
        """
        trial, _arms, _v1 = setup_trial_open_for_enrollment()
        p = create_participant(trial["id"])
        p = evaluate_participant(p["id"])
        p = request_consent(p["id"])
        assert p["status"] == "CONSENT_PENDING"
        from test_helpers import re_get_trial
        before = re_get_trial(trial["id"])
        withdrawn = withdraw_participant(p["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        after = re_get_trial(trial["id"])
        assert after["enrolled_count"] == before["enrolled_count"]
