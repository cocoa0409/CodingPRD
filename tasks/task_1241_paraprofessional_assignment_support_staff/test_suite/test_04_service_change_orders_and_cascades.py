"""Service change orders: revision loop, uniqueness, effectuate cascades (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_qualification,
    create_active_assignment,
    create_active_plan,
    create_active_student,
    create_change_order_payload,
    create_para,
    create_published_coverage_plan,
    create_student,
    create_verified_assignment,
    get_plan_version,
    propose_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


def _file_sco(api, student_id, change_type="MINUTES_CHANGE", reason="rev", **overrides):
    resp = api.create_change_order(
        create_change_order_payload(student_id, change_type, reason, **overrides), COORD
    )
    return validate_success(resp, 201)


def test_sco_return_revision_cycle_keeps_student_pending(api):
    """PRD §3.2: "A `DistrictStaffingAdmin` then reviews the order: approval moves it from `FILED` to `APPROVED`, and returning moves it from `APPROVED` back to `FILED` — a revision loop in which the order’s body is immutable but may be re-approved, with the student remaining `SERVICE_CHANGE_PENDING` throughout."

    Design: Corner/state_machines/sco_return_revision_cycle
    """
    plan, building, _ = create_active_plan()
    s1 = create_active_student(plan["id"], building["id"])
    sco = _file_sco(api, s1["id"], new_minutes_per_week=900)

    validate_success(api.approve_change_order(sco["id"], ADMIN))
    returned = validate_success(api.return_change_order(sco["id"], ADMIN))
    assert returned["status"] == "FILED"
    reapproved = validate_success(api.approve_change_order(sco["id"], ADMIN))
    assert reapproved["status"] == "APPROVED"
    student = validate_success(api.get_student(s1["id"], ANY))
    assert student["status"] == "SERVICE_CHANGE_PENDING"


def test_sco_effectuate_from_filed_is_rejected(api):
    """PRD §3.2: "Effectuation, performed by a `SpecialEdCoordinator`, moves an `APPROVED` order to `EFFECTIVE` and is only valid while the student still sits in `SERVICE_CHANGE_PENDING` (else `ERR_CHANGE_ORDER_INVALID_STATE`)."

    Design: Corner/state_machines/sco_effectuate_from_filed_returns_invalid_state
    """
    plan, building, _ = create_active_plan()
    s1 = create_active_student(plan["id"], building["id"])
    sco = _file_sco(api, s1["id"], new_minutes_per_week=900)
    assert sco["status"] == "FILED"
    resp = api.effectuate_change_order(sco["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_CHANGE_ORDER_INVALID_STATE)


def test_second_open_change_order_rejected(api):
    """PRD §3.2: "Filing succeeds into status `FILED` and immediately moves the student from `ACTIVE_IEP` to `SERVICE_CHANGE_PENDING`."
    PRD §3.2: "Filing an order requires the student to be `ACTIVE_IEP` (a student in `SERVICE_CHANGE_PENDING` or already `EXITED` is rejected with `ERR_STUDENT_NOT_ASSIGNABLE`) and requires that no other order for the student is sitting in `FILED` or `APPROVED` (else `ERR_OPEN_CHANGE_ORDER_EXISTS`)."
    PRD §2.7: "Fourth come the state checks, in three sub-steps: ... then the target entity must sit in exactly the from-state its transition declares" — state checks precede the sixth-priority uniqueness rules, so a second filing while the first sits open surfaces the student-state error.

    Design: Corner/validations/open_change_order_uniqueness
    """
    plan, building, _ = create_active_plan()
    s1 = create_active_student(plan["id"], building["id"])
    _file_sco(api, s1["id"], new_minutes_per_week=900, reason="first")
    resp = api.create_change_order(
        create_change_order_payload(s1["id"], "MINUTES_CHANGE", "second",
                                    new_minutes_per_week=600),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_ASSIGNABLE)


def test_service_change_effectuate_runs_three_hop_cascade(api):
    """PRD §3.2: "Either way, the effectuation fires the three-hop reassignment cascade. Hop one ends each of the student’s assignments in `PROPOSED`, `QUALIFICATION_VERIFIED`, `ACTIVE`, or `SUSPENDED` with `end_reason` `SERVICE_CHANGED`, returning each ended assignment’s `weekly_minutes` to its para’s `weekly_scheduled_minutes` and its `projected_weekly_cost_cents` to the plan’s `committed_cost_cents` (a `SUSPENDED` assignment has already released both, so only its `funding_status` moves). Hop two: the drop in a para’s `weekly_scheduled_minutes` may flip that para’s `benefit_eligible` to false. Hop three: such a flip re-costs the para’s remaining `PROPOSED` and `QUALIFICATION_VERIFIED` assignments at the non-surcharged effective rate — `daily_cost_cents` and `projected_weekly_cost_cents` are recomputed — and the plan’s `committed_cost_cents` is adjusted by the resulting delta."

    Design: Difficulty/transitive_cascade/service_change_cascade_depth3
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    # A1 ACTIVE: 380 min/day Mon-Fri (480-860) = 1900 min/wk; projected 1900 >= 1800
    # -> surcharged rate 2400 -> daily 15200, weekly 76000
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=1900)
    a1 = create_active_assignment(
        plan_id, s1["id"], p1["id"], b1, plan_v,
        daily_start_minute=480, daily_end_minute=860,
    )
    # A2 QUALIFICATION_VERIFIED: 56 min/day Mon-Fri (900-956) = 280 min/wk;
    # projected at create 1900+280 >= 1800 -> surcharged daily 2240, weekly 11200
    s2 = create_active_student(plan_id, b1, iep_minutes_per_week=280)
    a2 = create_verified_assignment(
        plan_id, s2["id"], p1["id"], b1,
        daily_start_minute=900, daily_end_minute=956,
    )
    assert a2["daily_cost_cents"] == 2240
    para_mid = validate_success(api.get_para(p1["id"], ANY))
    assert para_mid["weekly_scheduled_minutes"] == 1900
    assert para_mid["benefit_eligible"] is True

    sco = _file_sco(api, s1["id"], reason="IEP revision reduces service minutes",
                    new_minutes_per_week=100)
    validate_success(api.approve_change_order(sco["id"], ADMIN))
    validate_success(api.effectuate_change_order(sco["id"], COORD))

    a1_after = validate_success(api.get_assignment(a1["id"], ANY))
    assert a1_after["status"] == "ENDED"
    assert a1_after["end_reason"] == "SERVICE_CHANGED"
    para_after = validate_success(api.get_para(p1["id"], ANY))
    assert para_after["weekly_scheduled_minutes"] == 0
    assert para_after["benefit_eligible"] is False
    a2_after = validate_success(api.get_assignment(a2["id"], ANY))
    assert a2_after["daily_cost_cents"] == 1867  # round_half_up(56/60 * 2000)
    assert a2_after["projected_weekly_cost_cents"] == 9335
    plan_after = validate_success(api.get_plan(plan_id, ANY))
    assert plan_after["committed_cost_cents"] == 9335  # 87200 - 76000 - (11200-9335)
    student_after = validate_success(api.get_student(s1["id"], ANY))
    assert student_after["iep_minutes_per_week"] == 100
    assert student_after["status"] == "ACTIVE_IEP"


def test_service_change_exit_ends_student_and_assignments(api):
    """PRD §3.2: "On effectuation the student’s record absorbs the order’s new values — minutes, qualification, or building per the `change_type` — and, for every type other than `EXIT`, the student returns to `ACTIVE_IEP`; an `EXIT` order instead moves the student to `EXITED`."
    PRD §3.2: "Hop one ends each of the student’s assignments in `PROPOSED`, `QUALIFICATION_VERIFIED`, `ACTIVE`, or `SUSPENDED` with `end_reason` `SERVICE_CHANGED`, returning each ended assignment’s `weekly_minutes` to its para’s `weekly_scheduled_minutes` and its `projected_weekly_cost_cents` to the plan’s `committed_cost_cents` (a `SUSPENDED` assignment has already released both, so only its `funding_status` moves)."

    Design: Corner/state_machines/service_change_exit_ends_student_and_assignments
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)

    sco = _file_sco(api, s1["id"], change_type="EXIT", reason="student leaves district")
    validate_success(api.approve_change_order(sco["id"], ADMIN))
    validate_success(api.effectuate_change_order(sco["id"], COORD))

    student = validate_success(api.get_student(s1["id"], ANY))
    assert student["status"] == "EXITED"
    a1_after = validate_success(api.get_assignment(a1["id"], ANY))
    assert a1_after["status"] == "ENDED"
    assert a1_after["end_reason"] == "SERVICE_CHANGED"


def test_qualification_revoke_cascades_to_suspension_and_absence(api):
    """PRD §3.3: "Revoking a qualification sets its entry’s `revoked` flag true and fires a safety cascade: every `ACTIVE` assignment of that para whose `required_qualification_snapshot` equals the revoked credential moves to `SUSPENDED` under the release cascade of §3.5, and for each such assignment, if the current logical weekday is among its `days_of_week` and a `PUBLISHED` coverage plan exists for the assignment’s building and the current date, an absence report is auto-created in `REPORTED` and the coverage plan’s posture is recomputed."

    Design: Difficulty/transitive_cascade/training_revoke_cascade_depth2
    """
    # 2026-05-01 is a Friday, inside A1's Mon-Fri days_of_week
    validate_success(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    add_qualification(p1["id"], "BEHAVIOR_SUPPORT", "2026-01-10", expires_on="2027-01-10")
    s1 = create_active_student(
        plan_id, b1, iep_service_level="ONE_TO_ONE", required_qualification="BEHAVIOR_SUPPORT"
    )
    # ONE_TO_ONE + BEHAVIOR_SUPPORT at wage 2000 -> rate 2250, daily 11250, weekly 56250
    a1 = create_active_assignment(
        plan_id, s1["id"], p1["id"], b1, plan_v,
        start_date="2026-05-01", end_date="2026-06-30",
    )
    cp = create_published_coverage_plan(plan_id, b1, "2026-05-01")

    validate_success(
        api.revoke_qualification(p1["id"], {"qualification": "BEHAVIOR_SUPPORT"}, ADMIN)
    )

    a1_after = validate_success(api.get_assignment(a1["id"], ANY))
    assert a1_after["status"] == "SUSPENDED"
    para_after = validate_success(api.get_para(p1["id"], ANY))
    assert para_after["weekly_scheduled_minutes"] == 0
    absences = validate_success(
        api.list_absences(ANY, params={"assignment_id": a1["id"]})
    )
    assert isinstance(absences, list) and len(absences) == 1
    assert absences[0]["status"] == "REPORTED"
    assert absences[0]["coverage_plan_id"] == cp["id"]
    cp_after = validate_success(api.get_coverage_plan(cp["id"], ANY))
    assert cp_after["coverage_posture"] == "GAPS_OPEN"
    plan_after = validate_success(api.get_plan(plan_id, ANY))
    assert plan_after["committed_cost_cents"] == 0  # 56250 released


def test_qualification_revoke_without_coverage_plan_creates_no_absence(api):
    """PRD §3.3: "Revoking a qualification sets its entry’s `revoked` flag true and fires a safety cascade: every `ACTIVE` assignment of that para whose `required_qualification_snapshot` equals the revoked credential moves to `SUSPENDED` under the release cascade of §3.5, and for each such assignment, if the current logical weekday is among its `days_of_week` and a `PUBLISHED` coverage plan exists for the assignment’s building and the current date, an absence report is auto-created in `REPORTED` and the coverage plan’s posture is recomputed."

    Design: Difficulty/transitive_cascade/training_revoke_cascade_depth2
    """
    validate_success(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    add_qualification(p1["id"], "BEHAVIOR_SUPPORT", "2026-01-10", expires_on="2027-01-10")
    s1 = create_active_student(
        plan_id, b1, iep_service_level="ONE_TO_ONE", required_qualification="BEHAVIOR_SUPPORT"
    )
    a1 = create_active_assignment(
        plan_id, s1["id"], p1["id"], b1, plan_v,
        start_date="2026-05-01", end_date="2026-06-30",
    )
    # No coverage plan exists for (B1, 2026-05-01) -> the auto-absence branch
    # does not fire even though the suspension cascade does
    validate_success(api.revoke_qualification(p1["id"], {"qualification": "BEHAVIOR_SUPPORT"}, ADMIN))

    a1_after = validate_success(api.get_assignment(a1["id"], ANY))
    assert a1_after["status"] == "SUSPENDED"
    para_after = validate_success(api.get_para(p1["id"], ANY))
    assert para_after["weekly_scheduled_minutes"] == 0
    absences = validate_success(api.list_absences(ANY, params={"assignment_id": a1["id"]}))
    assert absences == []


def test_para_separation_ends_assignments_with_coordinator_end_reason(api):
    """PRD §3.3: "Moving to `SEPARATED` — from either `ACTIVE` or `ON_LEAVE` — is terminal and ends every non-`ENDED` assignment of the para with `end_reason` `COORDINATOR_ENDED`, running the same minutes-release, benefit-flip, and re-costing cascade as a service change."

    Design: Difficulty/transitive_cascade/service_change_cascade_depth3
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=1500)
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    s2 = create_active_student(plan_id, b1, iep_minutes_per_week=300)
    a2 = create_verified_assignment(
        plan_id, s2["id"], p1["id"], b1,
        daily_start_minute=800, daily_end_minute=860,
    )
    committed_pre = validate_success(api.get_plan(plan_id, ANY))["committed_cost_cents"]
    assert committed_pre > 0

    separated = validate_success(api.set_para_status(p1["id"], {"status": "SEPARATED"}, ADMIN))
    assert separated["status"] == "SEPARATED"
    for a in (a1, a2):
        after = validate_success(api.get_assignment(a["id"], ANY))
        assert after["status"] == "ENDED"
        assert after["end_reason"] == "COORDINATOR_ENDED"
    para_after = validate_success(api.get_para(p1["id"], ANY))
    assert para_after["weekly_scheduled_minutes"] == 0
    plan_after = validate_success(api.get_plan(plan_id, ANY))
    assert plan_after["committed_cost_cents"] == 0
