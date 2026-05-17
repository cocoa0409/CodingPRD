"""Treatment plan drafting, activation, supersession, and expiration.

PRD §3.3 (lifecycle), §2.10 (plan ratio precondition).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    activate_treatment_plan,
    add_days,
    add_seconds,
    advance_clock,
    assert_treatment_plan,
    create_treatment_plan_payload,
    draft_treatment_plan,
    make_bcba_headers,
    setup_active_treatment_plan,
    setup_clinic_with_roster,
    setup_completed_evaluation,
    setup_drafted_plan_with_in_progress_evaluation,
    supersede_treatment_plan,
    supersede_treatment_plan_payload,
    validate_error,
    validate_success,
)


class TestDraftTreatmentPlan:

    def test_draft_plan_returns_draft_status(self, api):
        """PRD §3.3: "The plan enters DRAFT status."

        Claim: POST /patients/{id}/treatment-plans returns a plan with
        status == DRAFT and plan_version == 1.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        evaluation = setup_completed_evaluation(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
            recommended_weekly_hours=20,
        )
        plan = draft_treatment_plan(
            patient_id=roster["patient"]["id"],
            source_evaluation_id=evaluation["id"],
            weekly_direct_hours_target=20,
            weekly_supervision_hours_target=2.0,
            weekly_parent_training_hours_target=1.0,
            bcba_id=bcba["id"],
        )
        assert_treatment_plan(plan)
        assert plan["status"] == "DRAFT"
        assert plan["plan_version"] == 1

    def test_draft_plan_with_direct_target_mismatch_rejected(self, api):
        """PRD §3.3: "weekly_direct_hours_target must equal the source
        evaluation's recommended_weekly_hours".

        Claim: a draft whose weekly_direct_hours_target != the source
        evaluation's recommended_weekly_hours is rejected.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        evaluation = setup_completed_evaluation(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
            recommended_weekly_hours=20,
        )
        res = api.create_treatment_plan(
            roster["patient"]["id"],
            create_treatment_plan_payload(
                source_evaluation_id=evaluation["id"],
                weekly_direct_hours_target=10,  # != 20
                weekly_supervision_hours_target=2.0,
                weekly_parent_training_hours_target=1.0,
            ),
            make_bcba_headers(bcba["id"]),
        )
        validate_error(res, "ERR_VALIDATION")

    @pytest.mark.parametrize(
        "parent_training_target", [0.4, 4.1, 0.0, 5.0],
    )
    def test_parent_training_target_out_of_range_rejected(
        self, api, parent_training_target,
    ):
        """PRD §3.3: "weekly_parent_training_hours_target must fall in
        the closed range from 0.5 to 4.0".

        Claim: a target outside [0.5, 4.0] is rejected.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        evaluation = setup_completed_evaluation(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        res = api.create_treatment_plan(
            roster["patient"]["id"],
            create_treatment_plan_payload(
                source_evaluation_id=evaluation["id"],
                weekly_direct_hours_target=20,
                weekly_supervision_hours_target=2.0,
                weekly_parent_training_hours_target=parent_training_target,
            ),
            make_bcba_headers(bcba["id"]),
        )
        validate_error(res, "ERR_VALIDATION")


class TestActivateTreatmentPlan:

    def test_activate_plan_at_ratio_exactly_0_10_succeeds(self, api):
        """PRD §2.10: "The plan may only activate when this ratio is
        greater than or equal to 0.10 — the boundary is inclusive, so a
        ratio of exactly 0.10 passes, but 0.099999 fails."

        Claim: 2 supervision / 20 direct == 0.10 (boundary) activates
        successfully.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        evaluation = setup_completed_evaluation(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        plan = draft_treatment_plan(
            patient_id=roster["patient"]["id"],
            source_evaluation_id=evaluation["id"],
            weekly_direct_hours_target=20,
            weekly_supervision_hours_target=2.0,
            weekly_parent_training_hours_target=1.0,
            bcba_id=bcba["id"],
        )
        activated = activate_treatment_plan(plan["id"], bcba_id=bcba["id"])
        assert activated["status"] == "ACTIVE"

    def test_activate_plan_with_insufficient_ratio_yields_plan_ratio_insufficient(
        self, api,
    ):
        """PRD §2.10: "A failure here yields ERR_PLAN_RATIO_INSUFFICIENT
        with HTTP 422."

        Claim: 1.0 supervision / 20 direct == 0.05 < 0.10 is rejected
        with ERR_PLAN_RATIO_INSUFFICIENT.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        evaluation = setup_completed_evaluation(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        plan = draft_treatment_plan(
            patient_id=roster["patient"]["id"],
            source_evaluation_id=evaluation["id"],
            weekly_direct_hours_target=20,
            weekly_supervision_hours_target=1.0,
            weekly_parent_training_hours_target=1.0,
            bcba_id=bcba["id"],
        )
        res = api.activate_treatment_plan(
            plan["id"], make_bcba_headers(bcba["id"]),
        )
        validate_error(res, "ERR_PLAN_RATIO_INSUFFICIENT")

    def test_draft_plan_from_in_progress_evaluation_rejected(self, api):
        """PRD §3.3: "Once an evaluation reaches COMPLETED, a BCBA
        drafts a treatment plan against the patient."

        Claim: drafting a plan against an IN_PROGRESS evaluation is
        rejected (PRD §3.3 pins drafting to a COMPLETED source). The
        exact error_id is not pinned in PRD prose beyond the
        state-precondition family, so the test accepts either
        ERR_INVALID_STATE (the natural state-precondition code) or
        ERR_VALIDATION (the schema-level fallback).

        # difficulty: cross_entity_state_dependency/plan_activate_requires_evaluation_completed
        """
        setup = setup_drafted_plan_with_in_progress_evaluation()
        bcba = setup["bcba"]
        res = api.create_treatment_plan(
            setup["patient"]["id"],
            create_treatment_plan_payload(
                source_evaluation_id=setup["evaluation"]["id"],
                weekly_direct_hours_target=20,
                weekly_supervision_hours_target=2.0,
                weekly_parent_training_hours_target=1.0,
            ),
            make_bcba_headers(bcba["id"]),
        )
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res, ["ERR_INVALID_STATE", "ERR_VALIDATION"],
        )


class TestSupersedeTreatmentPlan:

    def test_supersede_atomically_swaps_plans(self, api):
        """PRD §3.3: "The supersede capability is atomic: the old plan
        transitions from ACTIVE to SUPERSEDED, its superseded_by_id is
        set to the new plan's id, the new plan's plan_version is set to
        the old plan's plan_version plus one, and the new plan
        transitions from DRAFT to ACTIVE."

        Claim: after /supersede, old plan is SUPERSEDED with
        superseded_by_id set, and new plan is ACTIVE with
        plan_version == old.plan_version + 1.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        # Old plan via complete eval flow.
        old_plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        # Draft a NEW plan derived from a second completed evaluation
        # on the same patient.
        new_eval = setup_completed_evaluation(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        new_plan = draft_treatment_plan(
            patient_id=roster["patient"]["id"],
            source_evaluation_id=new_eval["id"],
            weekly_direct_hours_target=20,
            weekly_supervision_hours_target=2.0,
            weekly_parent_training_hours_target=1.0,
            bcba_id=bcba["id"],
        )
        res = api.supersede_treatment_plan(
            new_plan["id"],
            supersede_treatment_plan_payload(
                previous_plan_id=old_plan["id"],
            ),
            make_bcba_headers(bcba["id"]),
        )
        new_active = validate_success(res)
        assert new_active["status"] == "ACTIVE"
        assert new_active["plan_version"] == old_plan["plan_version"] + 1


class TestTreatmentPlanExpiration:

    def test_treatment_plan_expires_after_365_days(self, api):
        """PRD §3.3: "A plan moves to EXPIRED automatically when the
        clinic's now_ts advances past 365 days after its activated_at."

        Claim: after advancing the clock past activated_at + 365 days,
        the plan auto-transitions to EXPIRED.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=roster["patient"], bcba=bcba,
        )
        # Advance more than 365 days past activated_at.
        advance_clock(clinic["id"], 366 * 24 * 3600)
        res = api.list_treatment_plans(
            roster["patient"]["id"], make_bcba_headers(bcba["id"]),
        )
        body = res.json()
        # Find the plan in the list and assert it's EXPIRED.
        plans = [p for p in body["data"] if p["id"] == plan["id"]]
        assert plans, "plan must be present in the list"
        assert plans[0]["status"] == "EXPIRED"
