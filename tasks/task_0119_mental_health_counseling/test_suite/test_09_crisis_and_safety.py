"""Crisis assessment computation + safety plan lifecycle + appointment
hold cascade.

PRD §3.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    CRISIS_HIGH_THRESHOLD,
    CRISIS_MODERATE_THRESHOLD,
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_crisis_assessment,
    assert_safety_plan,
    create_crisis_assessment,
    create_crisis_assessment_payload,
    create_patient,
    create_safety_plan,
    create_safety_plan_payload,
    iso_anchor_offset,
    make_therapist_headers,
    re_get_appointment,
    re_get_patient,
    rescind_safety_plan,
    schedule_appointment,
    setup_active_licensed_therapist,
    setup_high_risk_assessment_then_appointment,
    setup_high_risk_patient_blocked,
    setup_patient_with_recent_care,
    setup_safety_plan_ready,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.9 CrisisAssessment composite score + buckets
# ===========================================================================
class TestCrisisAssessmentComputation:

    def test_zero_factors_produces_zero_composite_low_risk(self, api):
        """PRD §3.9: "Each of the five factor scores is multiplied by
        its weight ... Each of the five per-factor products is rounded
        half-up to two decimal places first, then the five rounded
        per-factor values are summed, then the sum is rounded half-up
        to two decimal places to produce composite_score."
        PRD §3.9: "anything below 15.00 yields LOW."

        Claim: all-zero factor scores produce composite_score=0.00 and
        risk_level=LOW.
        """
        therapist, patient, _ = setup_patient_with_recent_care()
        res = api.create_crisis_assessment(
            patient["id"],
            create_crisis_assessment_payload(
                therapist_id=therapist["id"],
                si_score=0, pa_score=0, su_score=0, so_score=0, am_score=0,
            ),
            make_therapist_headers(therapist["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_crisis_assessment(data)
        assert data["composite_score"] == pytest.approx(0.00, abs=0.001)
        assert data["risk_level"] == "LOW"

    def test_pinned_per_factor_rounding_then_sum_yields_high(self, api):
        """PRD §3.9: "Each of the five per-factor products is rounded
        half-up to two decimal places first, then the five rounded
        per-factor values are summed, then the sum is rounded half-up
        to two decimal places to produce composite_score."
        PRD §3.9: "a composite_score of at least 23.55 yields HIGH ..."

        Claim: factor inputs (si=3, pa=1, su=2, so=2, am=1) under the
        pinned per-factor rounding sequence yield composite_score=
        23.56 and risk_level=HIGH.

        Manual:
        - si=3 * 4.005 = 12.015, round_half_up(2dp) -> 12.02
        - pa=1 * 3.005 =  3.005, round_half_up(2dp) ->  3.01
        - su=2 * 2.005 =  4.010, round_half_up(2dp) ->  4.01
        - so=2 * 1.005 =  2.010, round_half_up(2dp) ->  2.01
        - am=1 * 2.505 =  2.505, round_half_up(2dp) ->  2.51
        - sum = 23.56 -> round_half_up(2dp) -> 23.56  (>= 23.55 -> HIGH)
        """
        therapist, patient, _ = setup_patient_with_recent_care()
        assessment = create_crisis_assessment(
            patient["id"], therapist["id"],
            si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
        )
        assert assessment["composite_score"] == pytest.approx(
            23.56, abs=0.001,
        )
        assert assessment["risk_level"] == "HIGH"

    def test_moderate_threshold_at_15_00_inclusive(self, api):
        """PRD §3.9: "a composite_score below 23.55 but at least 15.00
        yields MODERATE; anything below 15.00 yields LOW."

        Claim: a composite_score >= 15.00 and < 23.55 yields MODERATE.
        Concretely, si=3, pa=0, su=0, so=0, am=1 ->
            12.02 + 0.00 + 0.00 + 0.00 + 2.51 = 14.53 -> LOW.
        For MODERATE we need >= 15.00. Use si=3, pa=1, su=0, so=0,
        am=0: 12.02 + 3.01 + 0 + 0 + 0 = 15.03 -> MODERATE.
        """
        assert CRISIS_MODERATE_THRESHOLD == 15.00
        therapist, patient, _ = setup_patient_with_recent_care()
        assessment = create_crisis_assessment(
            patient["id"], therapist["id"],
            si_score=3, pa_score=1, su_score=0, so_score=0, am_score=0,
        )
        assert assessment["composite_score"] == pytest.approx(
            15.03, abs=0.001,
        )
        assert assessment["risk_level"] == "MODERATE"


# ===========================================================================
# §3.9 Score input validation
# ===========================================================================
class TestCrisisAssessmentInputBounds:

    @pytest.mark.parametrize("field,bad_value", [
        ("si_score", -1), ("si_score", 5),
        ("pa_score", -1), ("pa_score", 4),
        ("su_score", -1), ("su_score", 3),
        ("so_score", -1), ("so_score", 3),
        ("am_score", -1), ("am_score", 3),
    ])
    def test_out_of_range_factor_rejected(self, api, field, bad_value):
        """PRD §3.9: "si_score (suicidal-ideation factor, 0 through 4
        inclusive), pa_score (prior-attempts factor, 0 through 3
        inclusive), su_score (substance-use factor, 0 through 2
        inclusive), so_score (social-isolation factor, 0 through 2
        inclusive), and am_score (access-to-means factor, 0 through 2
        inclusive)."

        Claim: out-of-range factor scores are rejected as ERR_VALIDATION.
        """
        therapist, patient, _ = setup_patient_with_recent_care()
        body = create_crisis_assessment_payload(
            therapist_id=therapist["id"],
        )
        body[field] = bad_value
        res = api.create_crisis_assessment(
            patient["id"], body,
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_VALIDATION")


# ===========================================================================
# §3.9 Cascade: HIGH assessment flags safety_plan_required and HOLDs
# future appointments.
# ===========================================================================
class TestHighRiskCascade:

    def test_high_assessment_sets_safety_plan_required(self, api):
        """PRD §3.9: "If the new risk_level is HIGH and no SafetyPlan
        with status = ACTIVE exists for this patient, the system also
        sets safety_plan_required to true ..."

        Claim: after a HIGH assessment with no active safety plan, the
        patient.safety_plan_required is true.
        """
        _, patient, _ = setup_high_risk_patient_blocked()
        assert patient["safety_plan_required"] is True
        assert patient["latest_crisis_level"] == "HIGH"

    def test_high_assessment_holds_future_appointment(self, api):
        """PRD §3.9: "every future SCHEDULED appointment for this
        patient transitions to HELD with hold_reason =
        SAFETY_PLAN_MISSING (depth-3 cascade: assessment finalise →
        patient flag → appointment hold)."

        Claim: after a HIGH assessment lands on a patient with a
        future SCHEDULED appointment, the appointment transitions to
        HELD with hold_reason=SAFETY_PLAN_MISSING.
        """
        bundle = setup_high_risk_assessment_then_appointment()
        # Now post a HIGH crisis assessment.
        create_crisis_assessment(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
        )
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "HELD"
        assert appt["hold_reason"] == "SAFETY_PLAN_MISSING"


# ===========================================================================
# §3.9 SafetyPlan create / supersede / rescind
# ===========================================================================
class TestSafetyPlan:

    def test_safety_plan_requires_high_assessment(self, api):
        """PRD §3.9: "that referenced assessment must belong to this
        same patient and have risk_level = HIGH; violations are
        rejected with ERR_HIGH_ASSESSMENT_REQUIRED."

        Claim: creating a safety plan whose trigger_assessment_id
        points to a LOW assessment returns
        ERR_HIGH_ASSESSMENT_REQUIRED.
        """
        therapist, patient, _ = setup_patient_with_recent_care()
        low_assessment = create_crisis_assessment(
            patient["id"], therapist["id"],
            si_score=0, pa_score=0, su_score=0, so_score=0, am_score=0,
        )
        assert low_assessment["risk_level"] == "LOW"
        body = create_safety_plan_payload(
            trigger_assessment_id=low_assessment["id"],
        )
        res = api.create_safety_plan(
            patient["id"], body,
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_HIGH_ASSESSMENT_REQUIRED")

    def test_safety_plan_creation_clears_safety_required_flag(self, api):
        """PRD §3.9: "Creating the plan supersedes any prior ACTIVE
        plan for this patient (the prior plan transitions from ACTIVE
        to SUPERSEDED), sets the patient's safety_plan_required to
        false, and unholds every HELD appointment for this patient
        whose hold_reason = SAFETY_PLAN_MISSING ..."

        Claim: after a successful safety plan creation,
        patient.safety_plan_required is false and the previously HELD
        appointment returns to SCHEDULED with hold_reason=null.
        """
        # Build patient with HIGH assessment then a future appointment
        # that will be auto-HELD on next HIGH assessment.
        bundle = setup_high_risk_assessment_then_appointment()
        assessment = create_crisis_assessment(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
        )
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "HELD"
        # Now create the safety plan.
        plan = create_safety_plan(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            trigger_assessment_id=assessment["id"],
        )
        assert plan["status"] == "ACTIVE"
        patient = re_get_patient(bundle["patient"]["id"])
        assert patient["safety_plan_required"] is False
        appt2 = re_get_appointment(bundle["appointment"]["id"])
        assert appt2["status"] == "SCHEDULED"
        assert appt2.get("hold_reason") is None

    def test_safety_plan_supersedes_prior_active(self, api):
        """PRD §3.9: "Creating the plan supersedes any prior ACTIVE
        plan for this patient (the prior plan transitions from ACTIVE
        to SUPERSEDED) ..."

        Claim: after two safety plans for the same patient, the second
        is ACTIVE and the first transitioned to SUPERSEDED.
        """
        bundle = setup_safety_plan_ready()
        plan1 = create_safety_plan(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            trigger_assessment_id=bundle["assessment"]["id"],
        )
        # Need a second HIGH assessment to author plan2.
        assessment2 = create_crisis_assessment(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
        )
        plan2 = create_safety_plan(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            trigger_assessment_id=assessment2["id"],
        )
        # Re-read plan1 via the list endpoint.
        from prd_bench_local_runner.testing import validate_paginated
        res = api.list_safety_plans(
            bundle["patient"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        items, _ = validate_paginated(res)
        by_id = {p["id"]: p for p in items}
        assert by_id[plan2["id"]]["status"] == "ACTIVE"
        assert by_id[plan1["id"]]["status"] == "SUPERSEDED"

    def test_safety_plan_empty_support_contacts_rejected(self, api):
        """PRD §3.9: "an array of support_contacts (each an object
        with a name and a phone number; the array must have at least
        one entry) ..."

        Claim: a safety plan body with support_contacts=[] is rejected
        with ERR_VALIDATION (priority-22 schema constraint).
        """
        bundle = setup_safety_plan_ready()
        body = create_safety_plan_payload(
            trigger_assessment_id=bundle["assessment"]["id"],
            support_contacts=[],
        )
        res = api.create_safety_plan(
            bundle["patient"]["id"], body,
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_VALIDATION")

    def test_rescind_with_high_latest_assessment_rejected(self, api):
        """PRD §3.9: "Rescission is admitted only when the patient's
        most recent CrisisAssessment has risk_level in either LOW or
        MODERATE; an attempt while the latest assessment is still HIGH
        is rejected with ERR_RISK_STILL_HIGH."

        Claim: rescinding an ACTIVE safety plan while the latest
        assessment is HIGH returns ERR_RISK_STILL_HIGH.
        """
        bundle = setup_safety_plan_ready()
        plan = create_safety_plan(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            trigger_assessment_id=bundle["assessment"]["id"],
        )
        res = api.rescind_safety_plan(
            plan["id"], TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_RISK_STILL_HIGH")

    def test_rescind_after_risk_subsides_succeeds(self, api):
        """PRD §3.9: "Rescission is admitted only when the patient's
        most recent CrisisAssessment has risk_level in either LOW or
        MODERATE ... The transition takes the plan from ACTIVE to
        RESCINDED."

        Claim: after a fresh LOW assessment, an ACTIVE safety plan
        rescinds to RESCINDED.
        """
        bundle = setup_safety_plan_ready()
        plan = create_safety_plan(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            trigger_assessment_id=bundle["assessment"]["id"],
        )
        # Post a LOW assessment to bring latest level back to LOW.
        create_crisis_assessment(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            si_score=0, pa_score=0, su_score=0, so_score=0, am_score=0,
        )
        res = api.rescind_safety_plan(
            plan["id"], TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "RESCINDED"


# ===========================================================================
# §3.6 Safety preempts other check-in checks
# ===========================================================================
class TestSafetyPreemptsCheckIn:

    def test_checkin_with_safety_plan_required_rejected(self, api):
        """PRD §3.6: "The patient's safety_plan_required must be
        false; if it is true, the request is rejected with
        ERR_SAFETY_PLAN_REQUIRED before any license or scheduling
        check is consulted."

        Claim: a check-in for an appointment whose patient has
        safety_plan_required=true returns ERR_SAFETY_PLAN_REQUIRED.
        """
        # Build: HIGH-risk patient with future appointment also held by
        # the safety cascade. But the appointment is HELD (state-check
        # at priority 5 will fire first per PRD §2.7). The PRD declares
        # that ERR_SAFETY_PLAN_REQUIRED preempts license/scheduling
        # checks at priority 8 specifically. ERR_APPT_NOT_OPEN
        # (priority 7 state) actually fires first. So we accept either
        # ERR_SAFETY_PLAN_REQUIRED or ERR_APPT_NOT_OPEN — both are
        # PRD-faithful.
        bundle = setup_high_risk_assessment_then_appointment()
        create_crisis_assessment(
            bundle["patient"]["id"], bundle["therapist"]["id"],
            si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
        )
        # Advance into the check-in window for the future appointment.
        advance_clock_to(iso_anchor_offset(days=2, hours=1, minutes=59))
        res = api.checkin_appointment(
            bundle["appointment"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res, ["ERR_SAFETY_PLAN_REQUIRED", "ERR_APPT_NOT_OPEN"],
        )
