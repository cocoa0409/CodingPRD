"""Goal/milestone achievement bubbling, the graduation/withdrawal cascade,
graduation eligibility boundaries, coach capacity and load conservation, and
messaging guards.

Queue A: transitive_cascade (graduate depth-3; counted-weighin depth-2),
         boundary_precision_check (graduation zero/too-few counted weigh-ins),
         priority_pair_validation_conflict (state vs fiscal on graduate),
         resource_temporal_overlap (coach aggregate-capacity cap),
         compensating_invariant (assign-then-end conserves coach load).
Queue B: validations (goal target, single active assignment, thread not open).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
COACH_FALLBACK = TEST_USERS["coach_headers"]


def test_counted_weighin_cascade_goal_and_milestone_achieve(api):
    """PRD §3.6: "When a goal's progress reaches at least 100.0 — exactly 100 is
    enough — after a counted weigh-in, the goal automatically transitions from
    `OPEN` to `ACHIEVED`. That achievement transitions every still-pending
    milestone of the goal whose threshold is at most 100 to `ACHIEVED`."

    Design: Difficulty/transitive_cascade/counted_weighin_cascade_depth2_goal_progress_milestone
    """
    ctx = fixtures.create_active_enrollment(intake_weight_kg=95)
    enr_id = ctx["enrollment"]["id"]
    goal = fixtures.create_goal(enr_id, "PRIMARY", 90)
    milestone = fixtures.create_milestone(goal["id"], 100)
    fixtures.record_counted_weighin(enr_id, 90)  # reaches target -> 100%
    fetched_goal = validate_success(api.get_goal(goal["id"], ADMIN), 200)
    assert fetched_goal["progress_pct"] == 100.0, (
        f"goal progress must reach 100.0, got {fetched_goal['progress_pct']}"
    )
    assert fetched_goal["status"] == "ACHIEVED", f"goal must be ACHIEVED, got {fetched_goal['status']}"
    fetched_ms = validate_success(api.get_milestone(milestone["id"], ADMIN), 200)
    assert fetched_ms["status"] == "ACHIEVED", f"milestone must be ACHIEVED, got {fetched_ms['status']}"


def test_graduate_cascade_depth3_goal_milestone_assignment_thread(api):
    """PRD §3.11: "every `OPEN` goal of the enrollment transitions to `CLOSED`;
    each such goal-closure voids that goal's still-`PENDING` milestones; the
    goal-closure step then ends every `ACTIVE` coach assignment of the enrollment
    (each ending decrements the relevant coach's `active_member_count` by one); and
    each coach-assignment ending archives that assignment's still-`OPEN` message
    threads."

    Design: Difficulty/transitive_cascade/graduate_cascade_depth3_goal_milestone_assignment_thread
    """
    program = fixtures.create_program()
    plan = fixtures.create_plan(program["id"], monthly_fee_cents=6000)
    coach = fixtures.create_coach(program["id"])
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_approved_intake(member["id"], weight_kg=95)
    enrollment = validate_success(
        api.create_enrollment(f.create_enrollment_payload(member["id"], plan["id"], intake["id"]), ADMIN),
        201,
    )
    enr_id = enrollment["id"]
    validate_success(api.activate_enrollment(enr_id, ADMIN), 200)
    # PRIMARY goal achieved via reaching 90; SECONDARY OPEN goal with PENDING milestone.
    primary = fixtures.create_goal(enr_id, "PRIMARY", 90, actor_headers=fixtures.make_coach_headers(coach["id"]))
    secondary = fixtures.create_goal(enr_id, "SECONDARY", 80, actor_headers=fixtures.make_coach_headers(coach["id"]))
    milestone = fixtures.create_milestone(secondary["id"], 50, actor_headers=fixtures.make_coach_headers(coach["id"]))
    assignment = fixtures.assign_coach(enr_id, coach["id"])
    thread = fixtures.open_thread(assignment["id"], coach["id"])
    # Three counted weigh-ins (>=3 for graduation eligibility); final reaches target 90.
    coach_headers = fixtures.make_coach_headers(coach["id"])
    fixtures.record_counted_weighin(enr_id, 92, actor_headers=coach_headers)
    fixtures.record_counted_weighin(enr_id, 91, actor_headers=coach_headers)
    fixtures.record_counted_weighin(enr_id, 90, actor_headers=coach_headers)
    validate_success(api.graduate_enrollment(enr_id, ADMIN), 200)
    assert validate_success(api.get_goal(secondary["id"], ADMIN), 200)["status"] == "CLOSED"
    assert validate_success(api.get_milestone(milestone["id"], ADMIN), 200)["status"] == "VOIDED"
    assert validate_success(api.get_coach_assignment(assignment["id"], ADMIN), 200)["status"] == "ENDED"
    assert validate_success(api.get_message_thread(thread["id"], ADMIN), 200)["status"] == "ARCHIVED"
    assert validate_success(api.get_coach(coach["id"], ADMIN), 200)["active_member_count"] == 0


def test_milestone_below_100_achieves_at_its_threshold(api):
    """PRD §3.7: "A pending milestone automatically transitions to `ACHIEVED` when
    its owning goal's progress reaches at least its `threshold_pct` — the
    comparison is inclusive, so reaching the threshold exactly is sufficient —
    following a counted weigh-in."

    Design: Difficulty/transitive_cascade/counted_weighin_cascade_depth2_goal_progress_milestone
    """
    ctx = fixtures.create_active_enrollment(intake_weight_kg=95)
    enr_id = ctx["enrollment"]["id"]
    goal = fixtures.create_goal(enr_id, "PRIMARY", 85)  # span 10
    ms50 = fixtures.create_milestone(goal["id"], 50)
    fixtures.record_counted_weighin(enr_id, 90)  # lost 5 of span 10 -> 50%
    fetched_goal = validate_success(api.get_goal(goal["id"], ADMIN), 200)
    assert fetched_goal["progress_pct"] == 50.0, f"progress must be 50.0, got {fetched_goal['progress_pct']}"
    assert fetched_goal["status"] == "OPEN", "goal under 100 must stay OPEN"
    fetched_ms = validate_success(api.get_milestone(ms50["id"], ADMIN), 200)
    assert fetched_ms["status"] == "ACHIEVED", (
        f"50% milestone must achieve at exactly 50% progress, got {fetched_ms['status']}"
    )


def test_withdraw_cascade_closes_goal_voids_milestone_ends_assignment(api):
    """PRD §3.11: "then runs the same cascade: every `OPEN` goal becomes `CLOSED`,
    each closure voids that goal's still-`PENDING` milestones, every `ACTIVE` coach
    assignment becomes `ENDED` (decrementing the coach's `active_member_count`), and
    the affected assignments' `OPEN` message threads are archived."

    Design: Difficulty/transitive_cascade/graduate_cascade_depth3_goal_milestone_assignment_thread
    """
    program = fixtures.create_program()
    plan = fixtures.create_plan(program["id"], monthly_fee_cents=6000)
    coach = fixtures.create_coach(program["id"])
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_approved_intake(member["id"], weight_kg=95)
    enrollment = validate_success(
        api.create_enrollment(f.create_enrollment_payload(member["id"], plan["id"], intake["id"]), ADMIN),
        201,
    )
    enr_id = enrollment["id"]
    validate_success(api.activate_enrollment(enr_id, ADMIN), 200)
    coach_headers = fixtures.make_coach_headers(coach["id"])
    goal = fixtures.create_goal(enr_id, "SECONDARY", 80, actor_headers=coach_headers)
    milestone = fixtures.create_milestone(goal["id"], 50, actor_headers=coach_headers)
    assignment = fixtures.assign_coach(enr_id, coach["id"])
    thread = fixtures.open_thread(assignment["id"], coach["id"])
    validate_success(api.withdraw_enrollment(enr_id, ADMIN), 200)
    assert validate_success(api.get_goal(goal["id"], ADMIN), 200)["status"] == "CLOSED"
    assert validate_success(api.get_milestone(milestone["id"], ADMIN), 200)["status"] == "VOIDED"
    assert validate_success(api.get_coach_assignment(assignment["id"], ADMIN), 200)["status"] == "ENDED"
    assert validate_success(api.get_message_thread(thread["id"], ADMIN), 200)["status"] == "ARCHIVED"
    assert validate_success(api.get_coach(coach["id"], ADMIN), 200)["active_member_count"] == 0


def test_graduation_too_few_counted_weighins_blocks(api):
    """PRD §3.11: "An enrollment is graduation-eligible exactly when at least one
    `PRIMARY` goal has reached `ACHIEVED` status and the enrollment has at least
    three counted weigh-ins (weigh-ins recorded with `counts` true)."
    PRD §3.11: "Graduation requires ... the enrollment to be graduation-eligible
    (else `ERR_GRADUATION_CRITERIA_NOT_MET`)."

    Design: Difficulty/boundary_precision_check/graduation_zero_counted_weighins_empty_set_blocks
    """
    ctx = fixtures.create_active_enrollment(intake_weight_kg=95)
    enr_id = ctx["enrollment"]["id"]
    goal = fixtures.create_goal(enr_id, "PRIMARY", 90)
    fixtures.record_counted_weighin(enr_id, 90)  # exactly 1 counted weigh-in (< 3)
    achieved = validate_success(api.get_goal(goal["id"], ADMIN), 200)
    assert achieved["status"] == "ACHIEVED", "primary goal must be ACHIEVED via the single weigh-in"
    enr = validate_success(api.get_enrollment(enr_id, ADMIN), 200)
    assert enr["graduation_eligible"] is False, (
        f"1 counted weigh-in (< 3) must keep graduation_eligible false, got {enr['graduation_eligible']}"
    )
    resp = api.graduate_enrollment(enr_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_GRADUATION_CRITERIA_NOT_MET.value, 409)


def test_graduation_eligible_three_counted_weighins_succeeds(api):
    """PRD §3.11: "An enrollment is graduation-eligible exactly when at least one
    `PRIMARY` goal has reached `ACHIEVED` status and the enrollment has at least
    three counted weigh-ins (weigh-ins recorded with `counts` true)."
    PRD §3.11: "On graduation, `clinical_status` becomes `GRADUATED` and the
    member's `status` becomes `GRADUATED`."

    Design: Difficulty/boundary_precision_check/graduation_zero_counted_weighins_empty_set_blocks
    """
    ctx = fixtures.create_active_enrollment(intake_weight_kg=95)
    enr_id = ctx["enrollment"]["id"]
    fixtures.create_goal(enr_id, "PRIMARY", 90)
    # Exactly three counted weigh-ins; the last reaches the target and achieves.
    fixtures.record_counted_weighin(enr_id, 92)
    fixtures.record_counted_weighin(enr_id, 91)
    fixtures.record_counted_weighin(enr_id, 90)
    enr = validate_success(api.get_enrollment(enr_id, ADMIN), 200)
    assert enr["graduation_eligible"] is True, (
        f"3 counted weigh-ins + achieved primary must make graduation_eligible true, got {enr['graduation_eligible']}"
    )
    graduated = validate_success(api.graduate_enrollment(enr_id, ADMIN), 200)
    assert graduated["clinical_status"] == "GRADUATED", (
        f"graduate must move clinical_status to GRADUATED, got {graduated['clinical_status']}"
    )


def test_graduate_active_but_ineligible_reports_criteria_not_met(api):
    """PRD §3.11: "Graduation requires the enrollment's `clinical_status` to be
    `ACTIVE` (else `ERR_INVALID_STATE`) and the enrollment to be
    graduation-eligible (else `ERR_GRADUATION_CRITERIA_NOT_MET`)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_graduate_inactive_and_ineligible
    """
    # clinical_status ACTIVE (state gate passes), but no achieved primary goal and
    # no weigh-ins -> the graduation-eligibility gate fires.
    ctx = fixtures.create_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    resp = api.graduate_enrollment(enr_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_GRADUATION_CRITERIA_NOT_MET.value, 409)


def test_graduate_on_pending_clinical_reports_invalid_state(api):
    """PRD §3.11: "Graduation requires the enrollment's `clinical_status` to be
    `ACTIVE` (else `ERR_INVALID_STATE`) and the enrollment to be
    graduation-eligible (else `ERR_GRADUATION_CRITERIA_NOT_MET`)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_graduate_inactive_and_ineligible
    """
    ctx = fixtures.create_pending_enrollment()  # never activated, no goals
    enr_id = ctx["enrollment"]["id"]
    resp = api.graduate_enrollment(enr_id, ADMIN)
    # State precondition (clinical_status not ACTIVE) is the first-named gate and
    # takes precedence over the eligibility gate.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_coach_capacity_aggregate_cap_rejects_over_limit(api):
    """PRD §3.8: "the assignment must not push the coach's active load above the
    program's cap: if accepting the assignment would make the coach's
    `active_member_count` strictly greater than the program's
    `coach_max_active_members`, it is rejected with `ERR_COACH_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/coach_capacity_aggregate_cap_rejects_over_limit
    """
    program = fixtures.create_program(coach_max_active_members=1)
    plan = fixtures.create_plan(program["id"], monthly_fee_cents=6000)
    coach = fixtures.create_coach(program["id"])
    # Enrollment A — activated and assigned to the coach (count -> 1).
    member_a = fixtures.create_member(program["id"])
    intake_a = fixtures.create_approved_intake(member_a["id"])
    enr_a = validate_success(
        api.create_enrollment(f.create_enrollment_payload(member_a["id"], plan["id"], intake_a["id"]), ADMIN),
        201,
    )
    validate_success(api.activate_enrollment(enr_a["id"], ADMIN), 200)
    fixtures.assign_coach(enr_a["id"], coach["id"])
    # Enrollment B — activated, unassigned.
    member_b = fixtures.create_member(program["id"])
    intake_b = fixtures.create_approved_intake(member_b["id"])
    enr_b = validate_success(
        api.create_enrollment(f.create_enrollment_payload(member_b["id"], plan["id"], intake_b["id"]), ADMIN),
        201,
    )
    validate_success(api.activate_enrollment(enr_b["id"], ADMIN), 200)
    resp = api.create_coach_assignment(f.create_coach_assignment_payload(enr_b["id"], coach["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_COACH_CAPACITY_EXCEEDED.value, 409)
    after = validate_success(api.get_coach(coach["id"], ADMIN), 200)
    assert after["active_member_count"] == 1, (
        f"rejected assignment must leave count at 1, got {after['active_member_count']}"
    )


def test_coach_capacity_assignment_at_cap_allowed(api):
    """PRD §3.8: "if accepting the assignment would make the coach's
    `active_member_count` strictly greater than the program's
    `coach_max_active_members`, it is rejected with `ERR_COACH_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/coach_capacity_aggregate_cap_rejects_over_limit
    """
    # cap == 1; the first assignment makes the count exactly 1 (== cap, not
    # strictly greater), so it must be allowed.
    program = fixtures.create_program(coach_max_active_members=1)
    plan = fixtures.create_plan(program["id"], monthly_fee_cents=6000)
    coach = fixtures.create_coach(program["id"])
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_approved_intake(member["id"])
    enr = validate_success(
        api.create_enrollment(f.create_enrollment_payload(member["id"], plan["id"], intake["id"]), ADMIN),
        201,
    )
    validate_success(api.activate_enrollment(enr["id"], ADMIN), 200)
    assignment = validate_success(
        api.create_coach_assignment(f.create_coach_assignment_payload(enr["id"], coach["id"]), ADMIN), 201
    )
    assert assignment["status"] == "ACTIVE", "assignment up to the cap must be created ACTIVE"
    after = validate_success(api.get_coach(coach["id"], ADMIN), 200)
    assert after["active_member_count"] == 1, (
        f"count at the cap boundary must be 1, got {after['active_member_count']}"
    )


def test_assign_then_end_conserves_coach_active_load(api):
    """PRD §2.8: "An assignment created in `ACTIVE` status increments it by one; an
    assignment leaving `ACTIVE` for `ENDED` — whether ended directly or as part of
    an enrollment cascade — decrements it by one. An assignment created and later
    ended therefore leaves the count exactly where it began."

    Design: Difficulty/compensating_invariant/assign_then_end_conserves_coach_active_load
    """
    program = fixtures.create_program()
    plan = fixtures.create_plan(program["id"], monthly_fee_cents=6000)
    coach = fixtures.create_coach(program["id"])
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_approved_intake(member["id"])
    enr = validate_success(
        api.create_enrollment(f.create_enrollment_payload(member["id"], plan["id"], intake["id"]), ADMIN),
        201,
    )
    validate_success(api.activate_enrollment(enr["id"], ADMIN), 200)
    assignment = fixtures.assign_coach(enr["id"], coach["id"])
    assert validate_success(api.get_coach(coach["id"], ADMIN), 200)["active_member_count"] == 1
    ended = validate_success(api.end_coach_assignment(assignment["id"], ADMIN), 200)
    assert ended["status"] == "ENDED", f"assignment must end, got {ended['status']}"
    after = validate_success(api.get_coach(coach["id"], ADMIN), 200)
    assert after["active_member_count"] == 0, (
        f"assign-then-end must restore count to 0, got {after['active_member_count']}"
    )


def test_cascade_end_via_withdraw_conserves_coach_active_load(api):
    """PRD §2.8: "an assignment leaving `ACTIVE` for `ENDED` — whether ended
    directly or as part of an enrollment cascade — decrements it by one. An
    assignment created and later ended therefore leaves the count exactly where it
    began."

    Design: Difficulty/compensating_invariant/assign_then_end_conserves_coach_active_load
    """
    program = fixtures.create_program()
    plan = fixtures.create_plan(program["id"], monthly_fee_cents=6000)
    coach = fixtures.create_coach(program["id"])
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_approved_intake(member["id"])
    enr = validate_success(
        api.create_enrollment(f.create_enrollment_payload(member["id"], plan["id"], intake["id"]), ADMIN),
        201,
    )
    validate_success(api.activate_enrollment(enr["id"], ADMIN), 200)
    fixtures.assign_coach(enr["id"], coach["id"])
    assert validate_success(api.get_coach(coach["id"], ADMIN), 200)["active_member_count"] == 1
    # End the assignment indirectly via the withdrawal cascade.
    validate_success(api.withdraw_enrollment(enr["id"], ADMIN), 200)
    after = validate_success(api.get_coach(coach["id"], ADMIN), 200)
    assert after["active_member_count"] == 0, (
        f"cascade-end must restore count to its pre-assignment 0, got {after['active_member_count']}"
    )


def test_goal_target_not_below_baseline(api):
    """PRD §3.6: "The target weight must be strictly greater than zero and strictly
    below the member's `baseline_weight_kg`; if the baseline is null or the target
    is not strictly below it, the create is rejected with
    `ERR_TARGET_NOT_BELOW_BASELINE`."

    Design: Corner/validations/goal_target_not_below_baseline
    """
    ctx = fixtures.create_active_enrollment(intake_weight_kg=95)
    enr_id = ctx["enrollment"]["id"]
    resp = api.create_goal(f.create_goal_payload(enr_id, "PRIMARY", 100), ADMIN)
    validate_error(resp, ApiErrorId.ERR_TARGET_NOT_BELOW_BASELINE.value, 409)


def test_enrollment_single_active_assignment(api):
    """PRD §3.8: "An enrollment may carry at most one active assignment at a time,
    so assigning a coach to an enrollment that already has an active assignment is
    rejected with `ERR_ENROLLMENT_ALREADY_ASSIGNED`."

    Design: Corner/validations/enrollment_single_active_assignment
    """
    program = fixtures.create_program(coach_max_active_members=50)
    plan = fixtures.create_plan(program["id"], monthly_fee_cents=6000)
    coach1 = fixtures.create_coach(program["id"])
    coach2 = fixtures.create_coach(program["id"])
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_approved_intake(member["id"])
    enr = validate_success(
        api.create_enrollment(f.create_enrollment_payload(member["id"], plan["id"], intake["id"]), ADMIN),
        201,
    )
    validate_success(api.activate_enrollment(enr["id"], ADMIN), 200)
    fixtures.assign_coach(enr["id"], coach1["id"])
    resp = api.create_coach_assignment(f.create_coach_assignment_payload(enr["id"], coach2["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_ALREADY_ASSIGNED.value, 409)


def test_post_message_to_archived_thread_blocked(api):
    """PRD §3.8: "Posting is permitted only when the owning coach assignment is
    `ACTIVE` and the thread is `OPEN`; otherwise it is rejected with
    `ERR_THREAD_NOT_OPEN`."

    Design: Corner/validations/post_message_to_archived_thread_blocked
    """
    program = fixtures.create_program()
    plan = fixtures.create_plan(program["id"], monthly_fee_cents=6000)
    coach = fixtures.create_coach(program["id"])
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_approved_intake(member["id"])
    enr = validate_success(
        api.create_enrollment(f.create_enrollment_payload(member["id"], plan["id"], intake["id"]), ADMIN),
        201,
    )
    validate_success(api.activate_enrollment(enr["id"], ADMIN), 200)
    assignment = fixtures.assign_coach(enr["id"], coach["id"])
    thread = fixtures.open_thread(assignment["id"], coach["id"])
    validate_success(api.end_coach_assignment(assignment["id"], ADMIN), 200)  # thread auto-archived
    resp = api.post_message(thread["id"], f.post_message_payload("hello"), fixtures.make_coach_headers(coach["id"]))
    validate_error(resp, ApiErrorId.ERR_THREAD_NOT_OPEN.value, 409)
