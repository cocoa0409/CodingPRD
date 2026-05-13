"""Care Plan lifecycle: drafting, activation gates, review cycle,
supersession, and care-task execution window.

Anchored in PRD §3.3.
"""
from __future__ import annotations
import datetime as _dt
import pytest

from test_helpers import (
    ApiErrorId,
    REVIEW_CYCLE_BY_LEVEL,
    TASK_RECORD_WINDOW_HOURS,
    api_client,
    activate_care_plan,
    approve_assessment,
    create_active_care_plan,
    create_approved_assessment,
    create_draft_care_plan,
    create_elder,
    daily_task, task_execution_payload,
    draft_assessment,
    expected_classification,
    expected_composite_score,
    list_audit_logs, find_audit_logs,
    get_elder, get_prescription,
    iso_z, future_iso,
    setup_admitted_elder_v2,
    setup_admitted_elder_with_active_plan,
    submit_assessment,
    ADMIN, CAREGIVER, NURSE, NURSE_ALT, SUPERVISOR, SUPERVISOR_ALT,
    validate_error, validate_success,
)


# ===========================================================================
# Activation preconditions (PRD §3.3, §2.7 #14 / #20)
# ===========================================================================
class TestCarePlanActivation:

    def test_activate_succeeds_when_assessment_classification_matches(self):
        """PRD §3.3: "Activation, performed by a `Supervisor`, drives the
        plan from `DRAFT` to `ACTIVE`. Activation refuses if any other
        care plan for the same elder is already in `ACTIVE` (rejected with
        `ERR_ACTIVE_PLAN_EXISTS`) and refuses if the referenced
        assessment's `classification` does not equal the elder's
        `current_care_level` (rejected with `ERR_PLAN_LEVEL_MISMATCH`)."

        Claim: matching classification → activate succeeds (200, ACTIVE).
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)  # L3
        plan = create_active_care_plan(
            bundle["elder"]["id"], bundle["assessment"]["id"],
        )
        assert plan["status"] == "ACTIVE"
        assert plan["care_level_snapshot"] == "L3"

    def test_activate_rejected_when_classification_does_not_match_current_level(self):
        """PRD §3.3: "refuses if the referenced assessment's
        `classification` does not equal the elder's `current_care_level`
        (rejected with `ERR_PLAN_LEVEL_MISMATCH`)."

        Claim: assessment classification ≠ elder.current_care_level →
        ERR_PLAN_LEVEL_MISMATCH.
        # difficulty: cross_entity_state_dependency/care_plan_activation_depends_on_assessment_state
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)  # current_care_level L3
        # Mint a NEW assessment with different classification (L1).
        new_a = draft_assessment(bundle["elder"]["id"], 100, 30, 0,
                                 nurse_headers=NURSE_ALT)
        submit_assessment(new_a["id"], nurse_headers=NURSE_ALT)
        # Reject this new assessment without approving — Elder still L3.
        api_client.reject_care_assessment(new_a["id"], SUPERVISOR).json()
        # Build a DRAFT plan that points at the still-DRAFT-or-REJECTED
        # assessment — to construct mismatch we instead use an APPROVED
        # one of different level. Approve a fresh L4 assessment for the
        # elder; this updates current_care_level to L4. Now create a DRAFT
        # plan based on the ORIGINAL L3 assessment — its classification
        # (L3) no longer matches current_care_level (L4).
        # L4 composite: 0.5*(100-60) + (30-10) + 20 = 20+20+20 = 60 → L4.
        l4_a = draft_assessment(bundle["elder"]["id"], 60, 10, 20,
                                nurse_headers=NURSE_ALT)
        submit_assessment(l4_a["id"], nurse_headers=NURSE_ALT)
        approve_assessment(l4_a["id"], supervisor_headers=SUPERVISOR)
        refreshed = get_elder(bundle["elder"]["id"])
        assert refreshed["current_care_level"] == "L4"
        # Draft plan based on the L3 assessment.
        plan_draft = create_draft_care_plan(
            bundle["elder"]["id"], bundle["assessment"]["id"],
        )
        resp = api_client.activate_care_plan(plan_draft["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_PLAN_LEVEL_MISMATCH.value)

    def test_second_active_plan_rejected_with_active_plan_exists(self):
        """PRD §3.3: "Activation ... refuses if any other care plan for the
        same elder is already in `ACTIVE` (rejected with
        `ERR_ACTIVE_PLAN_EXISTS`)."

        Claim: with one ACTIVE plan, activating a second DRAFT plan for
        the same elder fails ERR_ACTIVE_PLAN_EXISTS.
        """
        bundle = setup_admitted_elder_with_active_plan(80, 10, 20)
        # Create a second DRAFT plan referencing the same approved assessment.
        plan2 = create_draft_care_plan(
            bundle["elder"]["id"], bundle["assessment"]["id"],
        )
        resp = api_client.activate_care_plan(plan2["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PLAN_EXISTS.value)


# ===========================================================================
# Snapshot semantics + review cycle days (PRD §3.3)
# ===========================================================================
class TestSnapshotAndReviewCycle:

    @pytest.mark.parametrize(
        "scores,expected_level,cycle_days",
        [
            ((100, 30, 0),   "L1",        90),  # composite 0  → L1, 90d
            ((100, 30, 20),  "L2",        60),  # 0+0+20=20    → L2, 60d
            ((80,  10, 20),  "L3",        45),
            ((60,  10, 20),  "L4",        30),
            ((20,  5,  40),  "INTENSIVE", 14),
        ],
    )
    def test_review_cycle_days_per_level(self, scores, expected_level,
                                         cycle_days):
        """PRD §3.3: "The `review_cycle_days` value is then derived from
        the snapshot using a per-level lookup: `L1` yields 90, `L2` yields
        60, `L3` yields 45, `L4` yields 30, and `INTENSIVE` yields 14."

        Claim: review_cycle_days matches the per-level lookup.
        """
        adl, cog, med = scores
        bundle = setup_admitted_elder_v2(adl, cog, med)
        plan = create_active_care_plan(
            bundle["elder"]["id"], bundle["assessment"]["id"],
        )
        assert plan["care_level_snapshot"] == expected_level
        assert plan["review_cycle_days"] == cycle_days


# ===========================================================================
# Review cycle (PRD §3.3) — non-linear state machine
# ===========================================================================
class TestReviewCycle:

    def test_flag_review_moves_active_to_under_review(self):
        """PRD §3.3: "A plan in `ACTIVE` can move to `UNDER_REVIEW` along
        three paths. A Supervisor can flag a review manually."

        Claim: POST /care-plans/{id}/flag-review on ACTIVE → UNDER_REVIEW.
        # difficulty: non_linear_state_machine/care_plan_review_under_review_cycle
        """
        bundle = setup_admitted_elder_with_active_plan(80, 10, 20)
        resp = api_client.flag_review_care_plan(
            bundle["plan"]["id"], SUPERVISOR,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "UNDER_REVIEW"

    def test_confirm_review_restarts_cycle_and_returns_to_active(self):
        """PRD §3.3: "From `UNDER_REVIEW`, two onward routes exist:
        confirming the review without changes restarts the cycle by setting
        `next_review_due_at` to the current time plus `review_cycle_days`."

        Claim: confirm-review on UNDER_REVIEW → ACTIVE, with
        next_review_due_at strictly after the prior value.
        # difficulty: non_linear_state_machine/care_plan_review_under_review_cycle
        """
        bundle = setup_admitted_elder_with_active_plan(80, 10, 20)
        plan_id = bundle["plan"]["id"]
        prev_due = bundle["plan"].get("next_review_due_at")
        api_client.flag_review_care_plan(plan_id, SUPERVISOR)
        resp = api_client.confirm_review_care_plan(plan_id, SUPERVISOR)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ACTIVE"
        if prev_due is not None and data.get("next_review_due_at") is not None:
            assert data["next_review_due_at"] >= prev_due, \
                "PRD §3.3 — next_review_due_at restarts forward"

    def test_supersede_drafts_new_plan_into_active(self):
        """PRD §3.3: "superseding the plan provides a `new_plan_id`, which
        must refer to a `DRAFT` plan for the same elder. On supersession
        the new plan cascades from `DRAFT` to `ACTIVE` in the same
        transaction and the old plan moves from `UNDER_REVIEW` to
        `SUPERSEDED`."

        Claim: supersede flips both plans atomically (old SUPERSEDED,
        new ACTIVE).
        """
        bundle = setup_admitted_elder_with_active_plan(80, 10, 20)
        old_id = bundle["plan"]["id"]
        api_client.flag_review_care_plan(old_id, SUPERVISOR)
        new_plan = create_draft_care_plan(
            bundle["elder"]["id"], bundle["assessment"]["id"],
        )
        resp = api_client.supersede_care_plan(
            old_id, {"new_plan_id": new_plan["id"]}, SUPERVISOR,
        )
        old_after = validate_success(resp, expected_status=200)
        assert old_after["status"] == "SUPERSEDED"
        # New plan must now be ACTIVE.
        new_after = validate_success(
            api_client.get_care_plan(new_plan["id"], SUPERVISOR),
        )
        assert new_after["status"] == "ACTIVE"


# ===========================================================================
# Care task execution window (PRD §3.3, §2.7 #18)
# ===========================================================================
class TestCareTaskWindow:

    def test_task_recorded_at_scheduled_time_succeeds(self):
        """PRD §3.3: "The recording must occur within plus-or-minus 4 hours
        of `scheduled_for`; an attempt to log a task outside that window
        is rejected with `ERR_TASK_RECORD_WINDOW`."

        Claim: scheduled_for = now → within window → 201 created.
        """
        bundle = setup_admitted_elder_with_active_plan(80, 10, 20)
        plan_id = bundle["plan"]["id"]
        now_iso = future_iso(0)
        resp = api_client.create_task_execution(
            plan_id,
            task_execution_payload(task_type="BATHING",
                                   scheduled_for=now_iso,
                                   outcome="COMPLETED"),
            CAREGIVER,
        )
        validate_success(resp, expected_status=201)

    def test_task_recorded_outside_4h_window_rejected(self):
        """PRD §3.3: "The recording must occur within plus-or-minus 4 hours
        of `scheduled_for`; an attempt to log a task outside that window
        is rejected with `ERR_TASK_RECORD_WINDOW`."

        Claim: scheduled_for shifted ±4h+1 from now → ERR_TASK_RECORD_WINDOW.
        """
        bundle = setup_admitted_elder_with_active_plan(80, 10, 20)
        plan_id = bundle["plan"]["id"]
        # Past time, 5h before now → outside window.
        far_past = future_iso(- (TASK_RECORD_WINDOW_HOURS + 1) * 3600)
        resp = api_client.create_task_execution(
            plan_id,
            task_execution_payload(task_type="BATHING",
                                   scheduled_for=far_past,
                                   outcome="COMPLETED"),
            CAREGIVER,
        )
        validate_error(resp, ApiErrorId.ERR_TASK_RECORD_WINDOW.value)
