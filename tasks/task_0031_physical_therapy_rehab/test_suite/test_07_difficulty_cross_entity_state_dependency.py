"""Difficulty Rule 7 — cross_entity_state_dependency.

Two cross-entity dependencies on different entity pairs:
  (A) Visit /complete needs parent POC in ACTIVE/RECERT_DUE — discharging the POC
      cancels the visit AND blocks /complete with ERR_INVALID_STATE.
  (B) MIPS create requires Patient.insurance_type=MEDICARE AND
      Therapist.medicare_provider_enrolled=true — a mismatch returns ERR_MIPS_ELIGIBILITY.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    setup_poc_with_grant,
    setup_active_poc,
    schedule_visit,
    complete_visit,
    record_discharge_assessment,
    discharge_poc,
    create_therapist,
    create_mips_measure_payload,
    complete_visit_payload,
    make_therapist_headers,
    TEST_USERS,
)


class TestVisitCompleteBlockedWhenParentPocDischarged:
    """Sequence: schedule a future visit → discharge the parent POC (visit cascades
    to CANCELLED) → operator races a /complete → ERR_INVALID_STATE.
    """

    def test_complete_on_visit_under_discharged_poc_returns_invalid_state(self, api):
        """PRD §3.5: "The transition is only permitted when the parent plan's `status`
        is `ACTIVE` or `RECERT_DUE`, the funding grant's `status` is `ACTIVE`, and today
        (UTC) is on or after the date portion of `scheduled_start_utc`."

        Design: Difficulty/cross_entity_state_dependency/visit_complete_blocked_when_parent_poc_discharged
        """
        ctx = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=10)
        th = ctx["therapist"]["id"]
        v = schedule_visit(
            ctx["grant"]["id"], th,
            scheduled_start_utc="2026-06-15T10:00:00Z",
            scheduled_end_utc="2026-06-15T11:00:00Z",
            planned_minutes=60, cpt_code="CPT_97110_THER_EX",
        )
        # Record discharge assessment then discharge the POC.
        record_discharge_assessment(
            ctx["poc"]["id"], th,
            final_functional_score=60, goals_met_count=5, total_goals_count=10,
            assessed_on="2026-06-10",
        )
        discharged = discharge_poc(ctx["poc"]["id"], th)
        assert discharged["status"] == "DISCHARGED"
        # Advance the clock past the scheduled date so the "today >= scheduled date"
        # gate is satisfied — only the parent-status gate should now reject.
        set_clock("2026-06-15T12:00:00Z")
        # Now try /complete — should fail ERR_INVALID_STATE (visit was cancelled
        # by the cascade, and POC is DISCHARGED).
        res = api.complete_visit(
            v["id"], complete_visit_payload(actual_minutes=60),
            make_therapist_headers(th),
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_visit_cancelled_by_discharge_cascade_visible_after_discharge(self, api):
        """PRD §3.6: "First hop: every `SCHEDULED` visit reachable through any
        `AuthorizationGrant` of this plan is cancelled (`SCHEDULED → CANCELLED`),
        with each cancelled visit having its `updated_at` refreshed and `version`
        incremented."

        Companion assertion to the cross-entity dependency: read the visit after
        discharge and confirm it is CANCELLED.

        Design: Difficulty/cross_entity_state_dependency/visit_complete_blocked_when_parent_poc_discharged
        """
        ctx = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=10)
        th = ctx["therapist"]["id"]
        v = schedule_visit(
            ctx["grant"]["id"], th,
            scheduled_start_utc="2026-06-15T10:00:00Z",
            scheduled_end_utc="2026-06-15T11:00:00Z",
            planned_minutes=60, cpt_code="CPT_97110_THER_EX",
        )
        record_discharge_assessment(
            ctx["poc"]["id"], th,
            final_functional_score=60, goals_met_count=5, total_goals_count=10,
            assessed_on="2026-06-10",
        )
        discharge_poc(ctx["poc"]["id"], th)
        v_after = validate_success(
            api.get_visit(v["id"], TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert v_after["status"] == "CANCELLED"


class TestMipsSubmitBlockedWhenTherapistNotMedicareEnrolled:
    """MIPS create with a reporting_therapist who has medicare_provider_enrolled=false
    fails with ERR_MIPS_ELIGIBILITY (the eligibility check applies at create).
    """

    def test_mips_create_rejects_non_enrolled_reporting_therapist(self, api):
        """PRD §3.7: "Two eligibility checks apply both at create and at submit: the
        patient's `insurance_type` must be `MEDICARE`, and the `Therapist` named by
        `reporting_therapist_id` must have `medicare_provider_enrolled` true.
        Violating either is rejected with `ERR_MIPS_ELIGIBILITY` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/mips_submit_blocked_when_therapist_not_medicare_enrolled
        """
        # Setup: MEDICARE patient, ACTIVE POC under a medicare-enrolled therapist A.
        ctx = setup_active_poc(
            insurance_type="MEDICARE", medicare_enrolled=True, functional_score=40,
        )
        # Create therapist B who is NOT medicare-enrolled.
        th_b = create_therapist(
            license_state="CA", medicare_provider_enrolled=False,
            full_name="T Not Enrolled",
        )
        # Create MIPS measure with reporting_therapist_id = therapist B.
        res = api.create_mips_measure(
            create_mips_measure_payload(
                patient_id=ctx["patient"]["id"],
                plan_of_care_id=ctx["poc"]["id"],
                reporting_therapist_id=th_b["id"],
                measure_code="MIPS128_FALL_RISK",
                performance_period_start="2026-06-01",
                performance_period_end="2026-06-30",
                numerator_met=True,
            ),
            make_therapist_headers(th_b["id"]),
        )
        validate_error(res, "ERR_MIPS_ELIGIBILITY", expected_status=422)

    def test_mips_create_rejects_non_medicare_patient(self, api):
        """PRD §3.7: "Two eligibility checks apply both at create and at submit: the
        patient's `insurance_type` must be `MEDICARE`, and the `Therapist` named by
        `reporting_therapist_id` must have `medicare_provider_enrolled` true.
        Violating either is rejected with `ERR_MIPS_ELIGIBILITY` (HTTP 422)."

        Companion: the OTHER half of the conjunctive eligibility — patient is COMMERCIAL.

        Design: Difficulty/cross_entity_state_dependency/mips_submit_blocked_when_therapist_not_medicare_enrolled
        """
        # COMMERCIAL patient (not MEDICARE), enrolled therapist.
        ctx = setup_active_poc(
            insurance_type="COMMERCIAL", medicare_enrolled=True, functional_score=40,
        )
        th = ctx["therapist"]["id"]
        res = api.create_mips_measure(
            create_mips_measure_payload(
                patient_id=ctx["patient"]["id"],
                plan_of_care_id=ctx["poc"]["id"],
                reporting_therapist_id=th,
                measure_code="MIPS128_FALL_RISK",
                performance_period_start="2026-06-01",
                performance_period_end="2026-06-30",
                numerator_met=True,
            ),
            make_therapist_headers(th),
        )
        validate_error(res, "ERR_MIPS_ELIGIBILITY", expected_status=422)
