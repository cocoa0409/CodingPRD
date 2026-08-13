"""Academic plans: admissibility, coverage arithmetic, credit budget, checkpoints."""
import pytest

from test_helpers import (
    AID_OFFICER, api_client, checkpoint_payload, close_and_evaluate,
    create_posted_enrollment, decide_appeal, get_student, list_notifications,
    make_student_headers, official_evaluation, plan_payload,
    setup_appeal_under_review, setup_approved_appeal, setup_plan_active,
    student_version, submit_appeal, validate_error, validate_paginated,
    validate_success,
)


def _list_plans_total(api, student_id) -> int:
    _rows, meta = validate_paginated(
        api.list_plans(AID_OFFICER, params={"student_id": student_id, "limit": 100}))
    return meta["total_count"]


def _checkpoint_for(api, plan_id, term_id) -> dict:
    data, _meta = validate_paginated(api.list_checkpoints(
        AID_OFFICER, params={"plan_id": plan_id, "term_id": term_id, "limit": 100}))
    assert len(data) == 1
    return data[0]


def _fail_plan_and_return_to_suspension(api, world):
    """Post a failing T3 grade line and evaluate: the T3 checkpoint goes MISSED,
    the plan fails, and the student drops back to SUSPENSION with a fresh T3
    evaluation row to appeal against."""
    student_id = world["student"]["id"]
    term3 = world["terms"][3]
    create_posted_enrollment(student_id, term3["id"], 12, 0, 0.0, 12)
    close_and_evaluate(term3["id"])
    assert get_student(student_id)["sap_status"] == "SUSPENSION", "setup invariant"
    return official_evaluation(student_id, term3["id"])


class TestPlanCoverageHalfOpenOverlap:
    """Half-open ordinal coverage: [start_seq, max_checkpoint_seq + 1)."""

    def _world(self, api):
        """Plan 1 ACTIVE over seqs [3,5), then failed at T3; a second appeal approved
        WITH_PLAN leaves the student PLAN_PENDING again."""
        world = setup_plan_active()
        evaluation_t3 = _fail_plan_and_return_to_suspension(api, world)
        student_id = world["student"]["id"]
        appeal2 = submit_appeal(student_id, evaluation_t3["id"],
                                student_version(student_id),
                                reason_category="FAMILY_EMERGENCY",
                                statement="Second appeal",
                                documents=[{"doc_type": "AFFIDAVIT",
                                            "description": "Affidavit"}])
        validate_success(api.screen_appeal(appeal2["id"], AID_OFFICER), 200)
        decide_appeal(appeal2["id"], "APPROVED", resolution="WITH_PLAN",
                      rationale="Second chance with plan")
        world["appeal2"] = appeal2
        world["student"] = get_student(student_id)
        assert world["student"]["sap_status"] == "PLAN_PENDING", "setup invariant"
        return world

    def test_plan_coverage_overlap_at_same_start_rejected(self, api):
        """PRD section 3.7: "the plan covers the half-open interval of term ordinals
        from `coverage_start_seq` — the start term's `seq` — up to but not including
        `coverage_end_seq_exclusive` — one greater than the largest checkpoint term
        `seq` — and that interval may not intersect the coverage of any other plan of
        the same student in any status, on pain of `ERR_PLAN_TERM_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/plan_term_coverage_half_open_overlap
        """
        world = self._world(api)
        student_id = world["student"]["id"]
        terms = world["terms"]
        # Plan 1 covered [3,5) and is FAILED; restarting at seq 3 still intersects.
        res = api.create_plan(
            plan_payload(student_id, world["appeal2"]["id"], terms[3]["id"], 24,
                         [checkpoint_payload(terms[3]["id"], 12),
                          checkpoint_payload(terms[4]["id"], 12)]),
            AID_OFFICER)
        validate_error(res, "ERR_PLAN_TERM_OVERLAP")

    def test_plan_coverage_adjacent_start_accepted(self, api):
        """PRD section 3.7: "strict adjacency, one plan ending exactly where the next
        begins, is allowed."
        PRD section 3.7: "A successfully created plan opens `ACTIVE` with every
        checkpoint `PENDING`, moves the student from `PLAN_PENDING` to `PLAN_ACTIVE`,
        and appends `PLAN_CREATED` and `STANDING_CHANGED`."

        Design: Difficulty/resource_temporal_overlap/plan_term_coverage_half_open_overlap
        """
        world = self._world(api)
        student_id = world["student"]["id"]
        terms = world["terms"]
        # Plan 1 covered [3,5); a plan starting at seq 5 is exactly adjacent.
        plan2 = validate_success(api.create_plan(
            plan_payload(student_id, world["appeal2"]["id"], terms[5]["id"], 24,
                         [checkpoint_payload(terms[5]["id"], 24)]),
            AID_OFFICER), 201)
        assert plan2["status"] == "ACTIVE"
        assert plan2["coverage_start_seq"] == 5
        assert plan2["coverage_end_seq_exclusive"] == 6
        assert get_student(student_id)["sap_status"] == "PLAN_ACTIVE"


class TestPlanRevisionConservesCreditBudget:
    """The plan credit budget is invariant under revise."""

    def test_balanced_revision_succeeds_and_conserves_budget(self, api):
        """PRD section 3.7: "While every checkpoint still stands `PENDING`, an
        `AidOfficer` may revise the plan, replacing the entire checkpoint list in one
        motion."
        PRD section 3.7: "The credit budget must balance: `total_required_credits`
        must equal the sum of the checkpoints' `required_earned_credits`, else
        `ERR_PLAN_CREDIT_MISMATCH`."

        Design: Difficulty/compensating_invariant/plan_revision_conserves_credit_budget
        """
        world = setup_plan_active()  # T3: 12, T4: 12, total 24
        plan = world["plan"]
        terms = world["terms"]

        revised = validate_success(api.revise_plan(
            plan["id"],
            {"checkpoints": [checkpoint_payload(terms[3]["id"], 10),
                             checkpoint_payload(terms[4]["id"], 14)]},
            AID_OFFICER), 200)
        assert revised["total_required_credits"] == 24, "the budget itself is invariant"
        assert _checkpoint_for(api, plan["id"], terms[3]["id"])[
            "required_earned_credits"] == 10
        assert _checkpoint_for(api, plan["id"], terms[4]["id"])[
            "required_earned_credits"] == 14

    def test_unbalanced_revision_rejected_leaving_plan_untouched(self, api):
        """PRD section 3.7: "The replacement list must still satisfy the credit
        invariant — its floors must sum to the unchanged `total_required_credits`,
        since the budget itself is invariant under revise — and a revision whose
        checkpoints sum elsewhere is rejected with `ERR_PLAN_CREDIT_MISMATCH`, leaving
        the plan untouched."

        Design: Difficulty/compensating_invariant/plan_revision_conserves_credit_budget
        """
        world = setup_plan_active()
        plan = world["plan"]
        terms = world["terms"]
        validate_success(api.revise_plan(
            plan["id"],
            {"checkpoints": [checkpoint_payload(terms[3]["id"], 10),
                             checkpoint_payload(terms[4]["id"], 14)]},
            AID_OFFICER), 200)

        res = api.revise_plan(
            plan["id"],
            {"checkpoints": [checkpoint_payload(terms[3]["id"], 10),
                             checkpoint_payload(terms[4]["id"], 15)]},
            AID_OFFICER)
        validate_error(res, "ERR_PLAN_CREDIT_MISMATCH")

        assert _checkpoint_for(api, plan["id"], terms[3]["id"])[
            "required_earned_credits"] == 10, "no partial write after the rejection"
        assert _checkpoint_for(api, plan["id"], terms[4]["id"])[
            "required_earned_credits"] == 14
        reread = validate_success(api.get_plan(plan["id"], AID_OFFICER), 200)
        assert reread["total_required_credits"] == 24
        assert reread["status"] == "ACTIVE"


def test_checkpoint_miss_fails_plan_and_suspends(api):
    """PRD section 3.7: "Any shortfall, including a pace that cannot be computed,
    makes the checkpoint `MISSED`"
    PRD section 3.7: "A `MISSED` outcome fails the plan — `ACTIVE` to `FAILED` — and
    drops the student back to `SUSPENSION` with a fresh appeal window and a fresh
    round of reminders; `PLAN_FAILED` and `STANDING_CHANGED` join the audit row set."

    Design: Corner/state_machines/checkpoint_miss_fails_plan_and_suspends
    """
    world = setup_plan_active()  # T3 checkpoint: gpa 2.0, pace 67.0, earned 12
    student_id = world["student"]["id"]
    term3 = world["terms"][3]
    # Term figures: GPA 2.500 passes but pace 50.00 < 67.0 and earned 6 < 12.
    create_posted_enrollment(student_id, term3["id"], 12, 6, 30.0, 12)
    close_and_evaluate(term3["id"])

    checkpoint = _checkpoint_for(api, world["plan"]["id"], term3["id"])
    assert checkpoint["outcome"] == "MISSED"
    assert checkpoint["actual_earned_credits"] == 6
    assert checkpoint["actual_term_pace_pct"] == pytest.approx(50.0)

    plan = validate_success(api.get_plan(world["plan"]["id"], AID_OFFICER), 200)
    assert plan["status"] == "FAILED"
    assert get_student(student_id)["sap_status"] == "SUSPENSION"

    plan_results = list_notifications({"student_id": student_id, "kind": "PLAN_RESULT"})
    assert len(plan_results) == 1
    assert plan_results[0]["status"] == "QUEUED"
    standing_changes = list_notifications(
        {"student_id": student_id, "kind": "STANDING_CHANGE", "status": "QUEUED"})
    assert len(standing_changes) >= 1, "a fresh standing-change notice was queued"


def test_checkpoint_boundary_exact_met(api):
    """PRD section 3.7: "The checkpoint is `MET` when the term GPA is null or at least
    `required_term_gpa`, and the term pace is non-null and at least
    `required_term_pace_pct`, and the term earned credits are at least
    `required_earned_credits` — all three comparisons inclusive, so an actual exactly
    equal to its floor counts as met."
    PRD section 3.7: "A `MET` outcome with later checkpoints still pending changes
    neither plan status nor standing: the student remains `PLAN_ACTIVE`"

    Design: Corner/calculations/checkpoint_boundary_exact_met
    """
    world = setup_plan_active(checkpoint_credits=(9, 9), required_term_gpa=3.0,
                              required_term_pace_pct=75.0)
    student_id = world["student"]["id"]
    term3 = world["terms"][3]
    # Term figures land exactly on every floor: GPA 3.000, pace 75.00, earned 9.
    create_posted_enrollment(student_id, term3["id"], 12, 9, 36.0, 12)
    close_and_evaluate(term3["id"])

    checkpoint = _checkpoint_for(api, world["plan"]["id"], term3["id"])
    assert checkpoint["actual_term_gpa"] == pytest.approx(3.0)
    assert checkpoint["actual_term_pace_pct"] == pytest.approx(75.0)
    assert checkpoint["actual_earned_credits"] == 9
    assert checkpoint["outcome"] == "MET", "all three comparisons are inclusive"

    plan = validate_success(api.get_plan(world["plan"]["id"], AID_OFFICER), 200)
    assert plan["status"] == "ACTIVE", "non-final MET leaves the plan running"
    assert get_student(student_id)["sap_status"] == "PLAN_ACTIVE"


def test_checkpoint_null_term_gpa_vacuous_pass(api):
    """PRD section 3.7: "The checkpoint is `MET` when the term GPA is null or at least
    `required_term_gpa`, and the term pace is non-null and at least
    `required_term_pace_pct`, and the term earned credits are at least
    `required_earned_credits`"
    PRD section 3.3: "Pass/fail coursework contributes its attempted and earned
    credits to the pace basis but contributes zero `gpa_hours` and zero
    `quality_points` to the GPA basis."

    Design: Corner/calculations/checkpoint_null_term_gpa_vacuous_pass
    """
    world = setup_plan_active(checkpoint_credits=(3, 3), required_term_gpa=2.0,
                              required_term_pace_pct=50.0)
    student_id = world["student"]["id"]
    term3 = world["terms"][3]
    # Pass/fail term: zero GPA hours -> null term GPA, which passes vacuously.
    create_posted_enrollment(student_id, term3["id"], 3, 3, 0.0, 0)
    close_and_evaluate(term3["id"])

    checkpoint = _checkpoint_for(api, world["plan"]["id"], term3["id"])
    assert checkpoint["actual_term_gpa"] is None
    assert checkpoint["actual_term_pace_pct"] == pytest.approx(100.0)
    assert checkpoint["outcome"] == "MET", "the GPA sub-check passes vacuously on null"


def test_plan_without_approved_appeal_rejected(api):
    """PRD section 3.7: "Creation is admissible only while the referenced appeal
    stands `APPROVED` with resolution `WITH_PLAN` and the student stands
    `PLAN_PENDING`; anything else fails with `ERR_PLAN_NOT_ALLOWED`."

    Design: Corner/validations/plan_without_approved_appeal_rejected
    """
    world = setup_appeal_under_review()  # appeal UNDER_REVIEW, student SUSPENSION
    student_id = world["student"]["id"]
    res = api.create_plan(
        plan_payload(student_id, world["appeal"]["id"], world["terms"][3]["id"], 12,
                     [checkpoint_payload(world["terms"][3]["id"], 12)]),
        AID_OFFICER)
    validate_error(res, "ERR_PLAN_NOT_ALLOWED")
    assert _list_plans_total(api, student_id) == 0


def test_plan_checkpoint_term_before_suspension_rejected(api):
    """PRD section 3.7: "And the checkpoint terms must hang together: their `seq`
    values must be contiguous starting at the start term's `seq`, each referenced term
    must exist, and the start term's `seq` must be strictly greater than the `seq` of
    the term whose suspension evaluation triggered the appeal, else
    `ERR_CHECKPOINT_TERM_INVALID`."

    Design: Corner/validations/plan_checkpoint_term_before_suspension_rejected
    """
    world = setup_approved_appeal(resolution="WITH_PLAN")
    student_id = world["student"]["id"]
    # The suspension term is seq 2; a plan starting at seq 2 is not strictly after it.
    res = api.create_plan(
        plan_payload(student_id, world["appeal"]["id"], world["terms"][2]["id"], 12,
                     [checkpoint_payload(world["terms"][2]["id"], 12)]),
        AID_OFFICER)
    validate_error(res, "ERR_CHECKPOINT_TERM_INVALID")
    assert _list_plans_total(api, student_id) == 0
