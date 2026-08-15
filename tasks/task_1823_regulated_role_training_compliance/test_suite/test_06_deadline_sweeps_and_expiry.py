"""Sweep-driven deadline transitions, notice dedupe, and validity expiry."""
from test_helpers import (
    TEST_USERS,
    add_requirement,
    assert_instant_equal,
    create_active_curriculum,
    create_employee,
    create_regulator,
    create_role,
    find_assignment,
    get_assignment,
    get_employee,
    list_assignment_escalations,
    list_assignments,
    run_sweep,
    set_clock,
    setup_employee_with_assignment,
    verify_assignment,
)

ADMIN = TEST_USERS["compliance_admin_headers"]


def _setup_hard_soft_pair():
    """One employee holding a HARD and a SOFT assignment, both due
    2026-08-05T09:00:00Z, regulator interval 10 / reminder 7."""
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(
        code="REG-ESC", name="Escalation Regulator",
        escalation_interval_days=10, reminder_days_before_due=7,
    )
    cur_h = create_active_curriculum(reg["id"], code="CUR-H", title="Hard Course")
    cur_s = create_active_curriculum(reg["id"], code="CUR-S", title="Soft Course")
    role = create_role(code="R-ESC", name="Escalation Role")
    add_requirement(role["id"], cur_h["id"], due_in_days=2, criticality="HARD")
    add_requirement(role["id"], cur_s["id"], due_in_days=2, criticality="SOFT")
    emp = create_employee("E-ESC-1", role["id"], full_name="Esc Emp")
    ah = find_assignment(emp["id"], curriculum_id=cur_h["id"])
    asg_s = find_assignment(emp["id"], curriculum_id=cur_s["id"])
    return reg, emp, ah, asg_s


class TestHardSoftAcceleration:
    def test_hard_escalates_at_half_interval_while_soft_stays_overdue(self, api):
        """PRD §3.5: "The threshold itself is the full escalation interval for a
        `SOFT` requirement and half the interval, rounded up to a whole day, for
        a `HARD` one — HARD-criticality training escalates to the compliance
        office twice as fast."
        PRD §3.5: "Past that threshold, strictly, it is `ESCALATED`; an instant
        exactly at the threshold stays `OVERDUE`."
        PRD §3.5: "Entering `ESCALATED` ensures *both* the level-2 notice
        (backfilling it when the stage was skipped outright) and a level-3
        notice of kind `ESCALATION_COMPLIANCE` addressed to the compliance
        office with a `null` recipient."

        Design: Difficulty/combinatorial_formula/escalation_threshold_hard_vs_soft_acceleration
        """
        _, emp, ah, asg_s = _setup_hard_soft_pair()
        set_clock("2026-08-10T09:00:01Z")  # due + 5d + 1s
        sweep = run_sweep()

        hard = get_assignment(ah["id"])
        soft = get_assignment(asg_s["id"])
        assert hard["deadline_status"] == "ESCALATED", (
            "HARD threshold ceil(10/2)=5d crossed"
        )
        assert soft["deadline_status"] == "OVERDUE", (
            "SOFT threshold 10d not yet crossed — same clock, different state"
        )
        assert sweep["notices_created"] == 3, (
            "HARD: level-2 + level-3 backfill; SOFT: level-2; no level-1 because "
            "no sweep ever observed DUE_SOON"
        )
        assert sweep["assignments_transitioned"] == 2

        hard_notices, _ = list_assignment_escalations(ah["id"])
        assert [n["level"] for n in hard_notices] == [2, 3], (
            "list ordered triggered_at ASC, level ASC"
        )
        assert hard_notices[1]["kind"] == "ESCALATION_COMPLIANCE"
        soft_notices, _ = list_assignment_escalations(asg_s["id"])
        assert len(soft_notices) == 1
        assert soft_notices[0]["level"] == 2
        assert soft_notices[0]["kind"] == "OVERDUE_MANAGER"

    def test_hard_escalation_sets_compliance_blocked(self, api):
        """PRD §3.5: "When a `HARD` requirement's assignment enters `ESCALATED`,
        the same sweep re-evaluates the employee's `compliance_blocked` to true
        and cascades the employee's `PENDING` attestations under `OPEN`
        campaigns into `BLOCKED` — the escalation ladder is wired directly into
        attestation standing."
        PRD §3.6: "the employee is blocked exactly when there exists one of
        their assignments whose requirement is `HARD`-critical, whose
        requirement's role is the employee's *current* role, and which either
        has `deadline_status` `ESCALATED`, or has `progress_status` `FAILED`
        with no later assignment of the same `role_requirement_id` reaching
        `VERIFIED_COMPLETED`"

        Design: Difficulty/combinatorial_formula/escalation_threshold_hard_vs_soft_acceleration
        """
        _, emp, ah, _ = _setup_hard_soft_pair()
        assert get_employee(emp["id"])["compliance_blocked"] is False
        set_clock("2026-08-10T09:00:01Z")
        run_sweep()
        assert get_assignment(ah["id"])["deadline_status"] == "ESCALATED"
        assert get_employee(emp["id"])["compliance_blocked"] is True


class TestOverdueBoundary:
    def _setup_b6b(self):
        return setup_employee_with_assignment(
            "B6B", escalation_interval_days=10, reminder_days_before_due=7,
            due_in_days=2,
        )

    def test_at_exact_due_instant_assignment_is_not_overdue(self, api):
        """PRD §3.5: "Once the current time is strictly later than `due_at` — an
        instant exactly equal to the due moment is *not* overdue — the
        assignment is `OVERDUE`, up to and including `due_at` plus the
        escalation threshold."
        PRD §3.5: "Entering `DUE_SOON` ensures a level-1 notice of kind
        `DUE_SOON_REMINDER` addressed to the assignee."

        Design: Difficulty/boundary_precision_check/sweep_overdue_requires_strictly_after_due
        """
        ctx = self._setup_b6b()
        asg = ctx["assignment"]
        assert_instant_equal(asg["base_due_at"], "2026-08-05T09:00:00Z", "base_due_at")

        set_clock("2026-08-05T09:00:00Z")  # exactly due_at
        sweep = run_sweep()
        current = get_assignment(asg["id"])
        assert current["deadline_status"] == "DUE_SOON", (
            "now == due_at exactly is NOT overdue — strict greater-than"
        )
        assert sweep["notices_created"] == 1, "level-1 DUE_SOON reminder fires"
        assert sweep["assignments_transitioned"] == 0, "no status change at the boundary"

    def test_one_second_past_due_flips_to_overdue(self, api):
        """PRD §3.5: "Once the current time is strictly later than `due_at` — an
        instant exactly equal to the due moment is *not* overdue — the
        assignment is `OVERDUE`, up to and including `due_at` plus the
        escalation threshold."
        PRD §3.5: "Entering `OVERDUE` ensures a level-2 notice of kind
        `OVERDUE_MANAGER` addressed to the assignee's manager — with
        `recipient_employee_id` left `null` when the employee has no manager."

        Design: Difficulty/boundary_precision_check/sweep_overdue_requires_strictly_after_due
        """
        ctx = self._setup_b6b()
        asg = ctx["assignment"]

        set_clock("2026-08-05T09:00:00Z")
        run_sweep()
        set_clock("2026-08-05T09:00:01Z")  # one second past due
        sweep = run_sweep()

        current = get_assignment(asg["id"])
        assert current["deadline_status"] == "OVERDUE", "one second past due flips it"
        assert sweep["notices_created"] == 1, "level-2 OVERDUE_MANAGER notice on crossing"
        assert sweep["assignments_transitioned"] == 1

        notices, _ = list_assignment_escalations(asg["id"])
        assert [n["level"] for n in notices] == [1, 2]
        assert notices[0]["kind"] == "DUE_SOON_REMINDER"
        assert notices[1]["kind"] == "OVERDUE_MANAGER"


def test_due_soon_notice_deduped_across_repeated_sweeps(api):
    """PRD §3.5: "Each stage transition the sweep observes generates an
    **EscalationNotice**, and notice creation is existence-deduped per
    assignment and level across notices of any status, so a stage never
    double-notifies."
    PRD §3.5: "Entering `DUE_SOON` ensures a level-1 notice of kind
    `DUE_SOON_REMINDER` addressed to the assignee."

    Design: Corner/state_machines/due_soon_notice_deduped_across_repeated_sweeps
    """
    ctx = setup_employee_with_assignment(
        "DD", escalation_interval_days=10, reminder_days_before_due=7, due_in_days=10,
    )
    asg, emp = ctx["assignment"], ctx["employee"]
    assert asg["deadline_status"] == "ON_TRACK", "10 days out is beyond the 7-day window"

    set_clock("2026-08-07T09:00:00Z")  # 6 days before due 2026-08-13
    first = run_sweep()
    assert first["notices_created"] == 1, "first sweep in window creates the reminder"
    second = run_sweep()
    assert second["notices_created"] == 0, "dedupe suppresses duplicates"

    notices, meta = list_assignment_escalations(asg["id"])
    assert meta["total_count"] == 1
    assert notices[0]["level"] == 1
    assert notices[0]["kind"] == "DUE_SOON_REMINDER"
    assert notices[0]["recipient_employee_id"] == emp["id"], "level-1 goes to the assignee"


def test_verified_assignment_expires_at_exact_expiry_and_recurs(api):
    """PRD §3.4: "Step 4 of the sweep moves a `VERIFIED_COMPLETED` assignment
    whose `expires_at` is set to `EXPIRED` once the current time reaches that
    instant — the boundary is inclusive, so at the exact expiry instant the
    assignment already stands expired, and the validity period covers the
    half-open interval from `completed_at` up to but not including `expires_at`."
    PRD §3.4: "When the expired assignment's requirement is still `ACTIVE`, its
    `recurrence` is `VALIDITY_CYCLE`, and the employee's `status` is `ACTIVE` or
    `ON_LEAVE`, the same sweep step immediately issues a fresh assignment for
    that requirement with `trigger_source` `RECURRENCE`, `assigned_at` equal to
    the sweep's clock reading, and a `FROZEN` deadline dimension when the
    employee is on leave — perpetual re-certification with no human touch."
    PRD §3.4: "Expiry decrements the employee's `verified_completed_count` by
    one."

    Design: Corner/state_machines/verified_assignment_expires_at_exact_expiry_and_recurs
    """
    ctx = setup_employee_with_assignment(
        "EXP", recurrence="VALIDITY_CYCLE", validity_months=1, due_in_days=5,
    )
    asg, emp = ctx["assignment"], ctx["employee"]
    verify_assignment(asg["id"], emp["id"], score_pct=90)

    verified = get_assignment(asg["id"])
    assert_instant_equal(verified["expires_at"], "2026-09-03T09:00:00Z", "expires_at")

    set_clock("2026-09-03T09:00:00Z")  # exactly the expiry instant
    sweep = run_sweep()
    assert sweep["assignments_expired"] == 1, "inclusive boundary: expired AT the instant"
    assert sweep["recurrences_created"] == 1

    assignments, meta = list_assignments({"employee_id": emp["id"]})
    assert meta["total_count"] == 2
    old, new = assignments[0], assignments[1]  # creation order ascending
    assert old["progress_status"] == "EXPIRED"
    assert new["progress_status"] == "ASSIGNED"
    assert new["trigger_source"] == "RECURRENCE"
    assert_instant_equal(new["base_due_at"], "2026-09-08T09:00:00Z", "recurrence due (+5d)")

    assert get_employee(emp["id"])["verified_completed_count"] == 0


def test_initial_only_assignment_never_expires(api):
    """PRD §3.4: "for `INITIAL_ONLY`, `expires_at` stays `null` and the
    completion never expires."
    PRD §3.4: "`INITIAL_ONLY` requirements never expire and never recur."

    Design: Corner/state_machines/initial_only_assignment_survives_clock_beyond_validity
    """
    ctx = setup_employee_with_assignment(
        "IO", recurrence="INITIAL_ONLY", validity_months=1, due_in_days=5,
    )
    asg, emp = ctx["assignment"], ctx["employee"]
    verify_assignment(asg["id"], emp["id"], score_pct=90)

    set_clock("2028-08-04T09:00:00Z")  # two years past the validity length
    sweep = run_sweep()
    assert sweep["assignments_expired"] == 0
    assert sweep["recurrences_created"] == 0

    current = get_assignment(asg["id"])
    assert current["progress_status"] == "VERIFIED_COMPLETED"
    assert current["expires_at"] is None
