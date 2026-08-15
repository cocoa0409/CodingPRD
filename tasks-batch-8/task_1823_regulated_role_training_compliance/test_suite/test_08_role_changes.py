"""Employee role changes: scheduled/synchronous apply, cancel, reverse, cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_completion,
    add_requirement,
    assert_instant_equal,
    create_active_curriculum,
    create_employee,
    create_regulator,
    create_role,
    create_role_change,
    find_assignment,
    get_employee,
    get_role_change_data,
    get_success_data,
    list_assignments,
    list_completions,
    run_sweep,
    set_clock,
    submit_completion,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["compliance_admin_headers"]
HR = TEST_USERS["hr_admin_headers"]


def _setup_role_change_cascade():
    """E-RC in R-OLD with A1 (CUR-RC1, SUBMITTED) and A2 (CUR-RC2, ASSIGNED);
    R-NEW shares only CUR-RC2; a SCHEDULED change to R-NEW exists."""
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-RC", name="RC Regulator")
    cur1 = create_active_curriculum(reg["id"], code="CUR-RC1", title="RC One")
    cur2 = create_active_curriculum(reg["id"], code="CUR-RC2", title="RC Two")
    r_old = create_role(code="R-OLD", name="Old Role")
    add_requirement(r_old["id"], cur1["id"], criticality="HARD")
    add_requirement(r_old["id"], cur2["id"], criticality="SOFT")
    r_new = create_role(code="R-NEW", name="New Role")
    add_requirement(r_new["id"], cur2["id"], criticality="SOFT")
    emp = create_employee("E-RC-1", r_old["id"], full_name="RC Emp")
    a1 = find_assignment(emp["id"], curriculum_id=cur1["id"])
    a2 = find_assignment(emp["id"], curriculum_id=cur2["id"])
    c1 = submit_completion(a1["id"], emp["id"], score_pct=90)
    rc = create_role_change(emp["id"], r_new["id"], effective_at="2026-08-03T10:00:00Z")
    return {"regulator": reg, "cur1": cur1, "cur2": cur2, "r_old": r_old,
            "r_new": r_new, "employee": emp, "a1": a1, "a2": a2, "c1": c1, "rc": rc}


class TestRoleChangeApplyCascade:
    def test_apply_flips_role_and_cancels_only_uncovered_assignments(self, api):
        """PRD §3.3: "The employee's `current_role_id` becomes the `to_role_id`
        and `applied_at` is stamped. Every non-terminal assignment the employee
        holds whose requirement's curriculum is *not* required by an `ACTIVE`
        requirement of the new role is cancelled — curricula shared between the
        old and new roles survive, so shared training is never redone — and any
        of their completion records still `PENDING_REVIEW` are voided by the
        system."
        PRD §3.3: "a future `effective_at` leaves the record `SCHEDULED`, and
        scheduled changes are applied *only* by step 1 of the sweep, once the
        current time reaches the effective instant — there is no other path from
        `SCHEDULED` to `APPLIED`."

        Design: Difficulty/transitive_cascade/role_change_apply_cascade_cancel_void_recompute
        """
        ctx = _setup_role_change_cascade()
        assert ctx["rc"]["status"] == "SCHEDULED", "effective_at in the future"

        set_clock("2026-08-03T10:00:00Z")
        sweep = run_sweep()
        assert sweep["role_changes_applied"] == 1
        assert sweep["assignments_transitioned"] == 0, (
            "cascade cancels are not sweep deadline transitions"
        )

        rc = get_role_change_data(ctx["rc"]["id"])
        assert rc["status"] == "APPLIED"
        assert_instant_equal(rc["applied_at"], "2026-08-03T10:00:00Z", "applied_at")

        employee = get_employee(ctx["employee"]["id"])
        assert employee["current_role_id"] == ctx["r_new"]["id"], "hop 1: role flipped"

        a1 = get_success_data(api.get_assignment(ctx["a1"]["id"], ADMIN), 200)
        a2 = get_success_data(api.get_assignment(ctx["a2"]["id"], ADMIN), 200)
        assert a1["progress_status"] == "CANCELLED", "CUR-RC1 not required by R-NEW"
        assert a2["progress_status"] == "ASSIGNED", "shared curriculum survives untouched"

    def test_cancellation_voids_pending_completion_and_creates_no_duplicate(self, api):
        """PRD §3.3: "and any of their completion records still `PENDING_REVIEW`
        are voided by the system. Then, for each `ACTIVE` requirement of the new
        role whose curriculum has no covering assignment (progress in
        `ASSIGNED`, `IN_PROGRESS`, `SUBMITTED`, or `VERIFIED_COMPLETED`,
        coverage again keyed by curriculum), a fresh assignment is created with
        `trigger_source` `ROLE_CHANGE` and `source_role_change_id` pointing back
        at the change record."

        Design: Difficulty/transitive_cascade/role_change_apply_cascade_cancel_void_recompute
        """
        ctx = _setup_role_change_cascade()
        set_clock("2026-08-03T10:00:00Z")
        run_sweep()

        records, meta = list_completions(ctx["a1"]["id"])
        assert meta["total_count"] == 1
        assert records[0]["review_status"] == "VOIDED", (
            "the cancellation itself voided the pending completion"
        )

        created, meta = list_assignments({"source_role_change_id": ctx["rc"]["id"]})
        assert meta["total_count"] == 0, (
            "R-NEW's only requirement is covered by the surviving shared-curriculum "
            "assignment, so no new assignment is created"
        )


def test_scheduled_role_change_not_applied_until_sweep(api):
    """PRD §3.3: "a future `effective_at` leaves the record `SCHEDULED`, and
    scheduled changes are applied *only* by step 1 of the sweep, once the
    current time reaches the effective instant — there is no other path from
    `SCHEDULED` to `APPLIED`."

    Design: Corner/complexity_layers/scheduled_role_change_not_applied_until_sweep
    """
    set_clock("2026-08-03T09:00:00Z")
    r1 = create_role(code="R-DA1", name="DA One")
    r2 = create_role(code="R-DA2", name="DA Two")
    emp = create_employee("E-DA-1", r1["id"], full_name="DA Emp")
    rc = create_role_change(emp["id"], r2["id"], effective_at="2026-08-05T00:00:00Z")
    assert rc["status"] == "SCHEDULED"

    set_clock("2026-08-06T00:00:00Z")  # past effective_at, but no sweep yet
    assert get_employee(emp["id"])["current_role_id"] == r1["id"]
    assert get_role_change_data(rc["id"])["status"] == "SCHEDULED", "deferred execution"

    sweep = run_sweep()
    assert sweep["role_changes_applied"] == 1
    assert get_employee(emp["id"])["current_role_id"] == r2["id"]
    applied = get_role_change_data(rc["id"])
    assert applied["status"] == "APPLIED"
    assert_instant_equal(applied["applied_at"], "2026-08-06T00:00:00Z", "sweep time")


def test_cancelled_role_change_is_never_applied(api):
    """PRD §3.3: "A scheduled change can be withdrawn by an `HRAdmin` only while
    it is still `SCHEDULED`; cancelling anything else fails with
    `ERR_ROLE_CHANGE_NOT_CANCELLABLE`."

    Design: Corner/state_machines/scheduled_role_change_cancel_then_sweep_does_not_apply
    """
    set_clock("2026-08-03T09:00:00Z")
    r1 = create_role(code="R-CX1", name="CX One")
    r2 = create_role(code="R-CX2", name="CX Two")
    emp = create_employee("E-CX-1", r1["id"], full_name="CX Emp")
    rc = create_role_change(emp["id"], r2["id"], effective_at="2026-08-05T00:00:00Z")
    assert rc["status"] == "SCHEDULED"

    cancelled = get_success_data(api.cancel_role_change(rc["id"], HR), 200)
    assert cancelled["status"] == "CANCELLED"

    set_clock("2026-08-06T00:00:00Z")
    sweep = run_sweep()
    assert sweep["role_changes_applied"] == 0, "cancelled changes are never applied"
    assert get_employee(emp["id"])["current_role_id"] == r1["id"]

    again = api.cancel_role_change(rc["id"], HR)
    validate_error(again, ApiErrorId.ERR_ROLE_CHANGE_NOT_CANCELLABLE.value)


def test_role_change_reverse_restores_role_and_cancels_created_assignments(api):
    """PRD §3.3: "Reversal moves the change record from `APPLIED` to its
    terminal `REVERSED` state, cancels the surviving non-terminal assignments
    that carry this change's `source_role_change_id` — voiding their
    `PENDING_REVIEW` completions — restores the employee's `current_role_id` to
    the role matching `from_role_code`, stamps `reversed_at`, and then creates
    assignments with `trigger_source` `REVERSAL` (and the same
    `source_role_change_id`) for each `ACTIVE` requirement of the restored role
    whose curriculum lacks a covering assignment, before recomputing
    `verified_completed_count` and `compliance_blocked`."

    Design: Corner/state_machines/role_change_reverse_restores_role_and_cancels_created_assignments
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-RV", name="RV Regulator")
    cur1 = create_active_curriculum(reg["id"], code="CUR-RV1", title="RV One")
    cur2 = create_active_curriculum(reg["id"], code="CUR-RV2", title="RV Two")
    r1 = create_role(code="R-RV1", name="RV Role One")
    add_requirement(r1["id"], cur1["id"])
    r2 = create_role(code="R-RV2", name="RV Role Two")
    add_requirement(r2["id"], cur2["id"])
    emp = create_employee("E-RV-1", r1["id"], full_name="RV Emp")

    rc = create_role_change(emp["id"], r2["id"], effective_at="2026-08-03T09:00:00Z")
    assert rc["status"] == "APPLIED", "effective_at <= now applies synchronously"

    set_clock("2026-08-04T09:00:00Z")
    reversed_rc = get_success_data(api.reverse_role_change(rc["id"], HR), 200)
    assert reversed_rc["status"] == "REVERSED"
    assert_instant_equal(reversed_rc["reversed_at"], "2026-08-04T09:00:00Z", "reversed_at")

    assert get_employee(emp["id"])["current_role_id"] == r1["id"], "role restored"

    new_role_assignments, meta = list_assignments(
        {"employee_id": emp["id"], "curriculum_id": cur2["id"]}
    )
    assert meta["total_count"] == 1
    assert new_role_assignments[0]["progress_status"] == "CANCELLED"
    assert new_role_assignments[0]["trigger_source"] == "ROLE_CHANGE", (
        "apply-created assignment compensated"
    )

    old_role_assignments, meta = list_assignments(
        {"employee_id": emp["id"], "curriculum_id": cur1["id"]}
    )
    assert meta["total_count"] == 2
    original, reversal = old_role_assignments[0], old_role_assignments[1]
    assert original["progress_status"] == "CANCELLED", "original stays cancelled"
    assert reversal["progress_status"] == "ASSIGNED"
    assert reversal["trigger_source"] == "REVERSAL"
    assert_instant_equal(reversal["base_due_at"], "2026-09-03T09:00:00Z", "due = +30d")


def test_synchronous_role_change_apply_immediately_visible(api):
    """PRD §3.3: "An `effective_at` at or before the current instant applies the
    change synchronously at creation; a future `effective_at` leaves the record
    `SCHEDULED`, and scheduled changes are applied *only* by step 1 of the
    sweep, once the current time reaches the effective instant — there is no
    other path from `SCHEDULED` to `APPLIED`."

    Design: Corner/consistency_model/synchronous_role_change_apply_immediately_visible
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-IM", name="IM Regulator")
    cur1 = create_active_curriculum(reg["id"], code="CUR-IM1", title="IM One")
    cur2 = create_active_curriculum(reg["id"], code="CUR-IM2", title="IM Two")
    r1 = create_role(code="R-IM1", name="IM One")
    add_requirement(r1["id"], cur1["id"])
    r2 = create_role(code="R-IM2", name="IM Two")
    add_requirement(r2["id"], cur2["id"])
    emp = create_employee("E-IM-1", r1["id"], full_name="IM Emp")

    rc = create_role_change(emp["id"], r2["id"], effective_at="2026-08-03T09:00:00Z")
    assert rc["status"] == "APPLIED", "APPLIED in the mutation's own response"

    assert get_employee(emp["id"])["current_role_id"] == r2["id"], (
        "visible on the immediate next read"
    )
    old_assignments, _ = list_assignments(
        {"employee_id": emp["id"], "curriculum_id": cur1["id"]}
    )
    assert old_assignments[0]["progress_status"] == "CANCELLED"
    new_assignments, meta = list_assignments(
        {"employee_id": emp["id"], "curriculum_id": cur2["id"]}
    )
    assert meta["total_count"] == 1
    assert new_assignments[0]["progress_status"] == "ASSIGNED"
    assert new_assignments[0]["trigger_source"] == "ROLE_CHANGE", "cascades already settled"


def test_role_change_reverse_blocked_by_state_and_verified_completion(api):
    """PRD §3.3: "An applied change can be reversed under tighter conditions,
    all enforced at reversal time: the record must be `APPLIED`
    (`ERR_ROLE_CHANGE_NOT_REVERSIBLE`); the current time must be no later than
    fourteen days after `applied_at` (`ERR_RETROACTIVE_LIMIT_EXCEEDED`); no
    completion record in `ACCEPTED` review status may exist on any assignment
    created by this change, since accepted training cannot be un-happened
    (`ERR_ROLE_CHANGE_NOT_REVERSIBLE` again); and a role whose code matches the
    snapshotted `from_role_code` must exist and be `ACTIVE`
    (`ERR_ROLE_NOT_ACTIVE`)."

    Design: Corner/errors/role_change_reverse_blocked_by_verified_completion
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-RVB", name="RVB Regulator")
    cur1 = create_active_curriculum(reg["id"], code="CUR-RVB1", title="RVB One")
    cur2 = create_active_curriculum(reg["id"], code="CUR-RVB2", title="RVB Two")
    r1 = create_role(code="R-RVB1", name="RVB One")
    add_requirement(r1["id"], cur1["id"])
    r2 = create_role(code="R-RVB2", name="RVB Two")
    add_requirement(r2["id"], cur2["id"])
    emp = create_employee("E-RVB-1", r1["id"], full_name="RVB Emp")

    rc1 = create_role_change(emp["id"], r2["id"], effective_at="2026-08-10T00:00:00Z")
    not_applied = api.reverse_role_change(rc1["id"], HR)
    validate_error(not_applied, ApiErrorId.ERR_ROLE_CHANGE_NOT_REVERSIBLE.value)

    get_success_data(api.cancel_role_change(rc1["id"], HR), 200)
    rc2 = create_role_change(emp["id"], r2["id"], effective_at="2026-08-03T09:00:00Z")
    assert rc2["status"] == "APPLIED"

    a_new = find_assignment(emp["id"], curriculum_id=cur2["id"])
    c_new = submit_completion(a_new["id"], emp["id"], score_pct=90)
    accept_completion(c_new["id"])

    blocked = api.reverse_role_change(rc2["id"], HR)
    validate_error(blocked, ApiErrorId.ERR_ROLE_CHANGE_NOT_REVERSIBLE.value)


def test_role_change_reverse_after_14_days_returns_retroactive_error(api):
    """PRD §3.3: "the current time must be no later than fourteen days after
    `applied_at` (`ERR_RETROACTIVE_LIMIT_EXCEEDED`)"

    Design: Corner/errors/role_change_reverse_after_14_days_returns_retroactive_error
    """
    set_clock("2026-08-03T09:00:00Z")
    r1 = create_role(code="R-RW1", name="RW One")
    r2 = create_role(code="R-RW2", name="RW Two")
    emp = create_employee("E-RW-1", r1["id"], full_name="RW Emp")
    rc = create_role_change(emp["id"], r2["id"], effective_at="2026-08-03T09:00:00Z")
    assert rc["status"] == "APPLIED"

    set_clock("2026-08-18T09:00:00Z")  # applied_at + 15 days
    resp = api.reverse_role_change(rc["id"], HR)
    validate_error(resp, ApiErrorId.ERR_RETROACTIVE_LIMIT_EXCEEDED.value)


def test_second_scheduled_role_change_rejected(api):
    """PRD §3.3: "the employee may have at most one `SCHEDULED` change at a time
    (`ERR_PENDING_ROLE_CHANGE_EXISTS`)"

    Design: Corner/validations/second_scheduled_role_change_rejected
    """
    set_clock("2026-08-03T09:00:00Z")
    r1 = create_role(code="R-SC1", name="SC One")
    r2 = create_role(code="R-SC2", name="SC Two")
    r3 = create_role(code="R-SC3", name="SC Three")
    emp = create_employee("E-SC-1", r1["id"], full_name="SC Emp")
    rc1 = create_role_change(emp["id"], r2["id"], effective_at="2026-08-10T00:00:00Z")
    assert rc1["status"] == "SCHEDULED"

    resp = api.create_role_change(
        emp["id"], {"to_role_id": r3["id"], "effective_at": "2026-08-11T00:00:00Z"}, HR,
    )
    validate_error(resp, ApiErrorId.ERR_PENDING_ROLE_CHANGE_EXISTS.value)


def test_role_change_to_same_role_rejected(api):
    """PRD §3.3: "the target role must differ from the employee's current role
    (`ERR_ROLE_UNCHANGED`)"

    Design: Corner/validations/role_change_to_same_role_rejected
    """
    set_clock("2026-08-03T09:00:00Z")
    r1 = create_role(code="R-SAME2", name="Same2")
    emp = create_employee("E-SAME2", r1["id"], full_name="Same Two")
    resp = api.create_role_change(
        emp["id"], {"to_role_id": r1["id"], "effective_at": "2026-08-10T00:00:00Z"}, HR,
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_UNCHANGED.value)


def test_role_change_to_retired_role_rejected(api):
    """PRD §3.3: "the target role must be `ACTIVE` (`ERR_ROLE_NOT_ACTIVE`)"

    Design: Corner/validations/role_change_to_retired_role_rejected
    """
    set_clock("2026-08-03T09:00:00Z")
    r1 = create_role(code="R-RT1", name="RT One")
    r2 = create_role(code="R-RT2", name="RT Two")
    retired = get_success_data(api.retire_role(r2["id"], ADMIN), 200)
    assert retired["status"] == "RETIRED"
    emp = create_employee("E-RT-1", r1["id"], full_name="RT Emp")

    resp = api.create_role_change(
        emp["id"], {"to_role_id": r2["id"], "effective_at": "2026-08-10T00:00:00Z"}, HR,
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_ACTIVE.value)


class TestTemporalPriority:
    def _dual_failure_call(self, api):
        """Retroactive beyond 30 days AND targeted at the current role."""
        set_clock("2026-08-03T09:00:00Z")
        role = create_role(code="R-SAME", name="Same Role")
        emp = create_employee("E-P5B-1", role["id"], full_name="P5B Emp")
        resp = api.create_role_change(
            emp["id"],
            {"to_role_id": role["id"], "effective_at": "2026-06-15T00:00:00Z"},
            HR,
        )
        return emp, resp

    def test_temporal_error_wins_over_role_unchanged(self, api):
        """PRD §2.9: "Temporal rules (priority 8) beat uniqueness and limit
        checks (priority 9): a role change that is both retroactive beyond the
        permitted thirty days and targeted at the employee's current role
        returns `ERR_RETROACTIVE_LIMIT_EXCEEDED`."
        PRD §3.3: "the `effective_at` may not be more than thirty days in the
        past (`ERR_RETROACTIVE_LIMIT_EXCEEDED`)"

        Design: Difficulty/priority_pair_validation_conflict/temporal_priority_beats_role_unchanged_constraint
        """
        _, resp = self._dual_failure_call(api)
        validate_error(resp, ApiErrorId.ERR_RETROACTIVE_LIMIT_EXCEEDED.value)

    def test_dual_failure_role_change_is_not_persisted(self, api):
        """PRD §2.9: "Temporal rules (priority 8) beat uniqueness and limit
        checks (priority 9): a role change that is both retroactive beyond the
        permitted thirty days and targeted at the employee's current role
        returns `ERR_RETROACTIVE_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_priority_beats_role_unchanged_constraint
        """
        emp, resp = self._dual_failure_call(api)
        validate_error(resp, ApiErrorId.ERR_RETROACTIVE_LIMIT_EXCEEDED.value)
        _, meta = validate_paginated(
            api.list_role_changes(ADMIN, params={"employee_id": emp["id"]})
        )
        assert meta["total_count"] == 0
