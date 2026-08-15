"""Compliance posture: HARD-escalation block cascade and notice acknowledgement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_requirement,
    create_active_curriculum,
    create_employee,
    create_regulator,
    create_role,
    find_assignment,
    get_assignment,
    get_attestation_data,
    get_employee,
    list_employee_escalations,
    make_employee_headers,
    make_manager_headers,
    run_sweep,
    set_clock,
    setup_open_campaign_with_attestation,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["compliance_admin_headers"]


def _setup_blocked_scenario():
    """Managed employee with a HARD assignment due 2026-08-05T09:00:00Z and a
    PENDING attestation under an OPEN campaign."""
    return setup_open_campaign_with_attestation(
        "BLK", criticality="HARD", due_in_days=2,
        escalation_interval_days=10, reminder_days_before_due=7,
    )


class TestHardEscalationBlockCascade:
    def test_escalation_blocks_employee_then_attestation(self, api):
        """PRD §3.5: "When a `HARD` requirement's assignment enters `ESCALATED`,
        the same sweep re-evaluates the employee's `compliance_blocked` to true
        and cascades the employee's `PENDING` attestations under `OPEN`
        campaigns into `BLOCKED` — the escalation ladder is wired directly into
        attestation standing."

        Design: Difficulty/transitive_cascade/hard_escalation_blocks_employee_then_attestation
        """
        ctx = _setup_blocked_scenario()
        emp, asg, att = ctx["employee"], ctx["assignment"], ctx["attestation"]
        assert att["status"] == "PENDING", "attestation starts PENDING before the sweep"

        set_clock("2026-08-10T09:00:01Z")  # due + ceil(10/2)d + 1s
        run_sweep()

        assert get_assignment(asg["id"])["deadline_status"] == "ESCALATED"
        assert get_employee(emp["id"])["compliance_blocked"] is True
        assert get_attestation_data(att["id"])["status"] == "BLOCKED", (
            "block cascades to the PENDING attestation under the OPEN campaign"
        )

    def test_sweep_counters_for_block_cascade(self, api):
        """PRD §2.5: "The sweep runs five steps in a pinned order: (1) apply due
        role changes whose effective instant has been reached; (2) flip
        employees onto or off of leave as leave windows begin or cease to cover
        the current instant, freezing or unfreezing their non-terminal
        assignments; (3) recompute deadline statuses, create escalation notices,
        and apply the HARD-escalation compliance-block cascade; (4) expire
        verified completions whose validity has elapsed and create recurrence
        assignments; (5) auto-close attestation campaigns whose window has
        passed, with the attendant expiry cascade."

        Design: Difficulty/transitive_cascade/hard_escalation_blocks_employee_then_attestation
        """
        _setup_blocked_scenario()
        set_clock("2026-08-10T09:00:01Z")
        sweep = run_sweep()
        assert sweep["assignments_transitioned"] == 1
        assert sweep["notices_created"] == 2, "level-2 + level-3 backfill"
        assert sweep["attestations_blocked"] == 1


def test_attest_on_blocked_attestation_returns_not_actionable(api):
    """PRD §3.6: "the attestation must be `PENDING` — `BLOCKED`, `EXPIRED`, and
    `ATTESTED` all draw `ERR_ATTESTATION_NOT_ACTIONABLE`"
    PRD §3.5: "When a `HARD` requirement's assignment enters `ESCALATED`, the
    same sweep re-evaluates the employee's `compliance_blocked` to true and
    cascades the employee's `PENDING` attestations under `OPEN` campaigns into
    `BLOCKED` — the escalation ladder is wired directly into attestation
    standing."

    Design: Corner/errors/attest_on_blocked_attestation_returns_not_actionable
    """
    ctx = _setup_blocked_scenario()
    emp, att = ctx["employee"], ctx["attestation"]
    set_clock("2026-08-10T09:00:01Z")
    run_sweep()

    current = get_attestation_data(att["id"])
    assert current["status"] == "BLOCKED", "HARD escalation cascaded"
    resp = api.attest(att["id"], make_employee_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_ATTESTATION_NOT_ACTIONABLE.value)


def test_manager_acknowledges_own_notice_others_forbidden(api):
    """PRD §3.5: "Acknowledgement requires the notice to be `OPEN`
    (`ERR_INVALID_STATE` on a second acknowledgement); for a notice with a
    non-null recipient, the caller must carry the `Manager` role and be that
    addressed employee (`ERR_OWNERSHIP_MISMATCH`); for a level-3 notice with its
    null recipient, only a `ComplianceAdmin` may acknowledge — anyone else draws
    `ERR_FORBIDDEN_ROLE`."
    PRD §3.5: "Entering `OVERDUE` ensures a level-2 notice of kind
    `OVERDUE_MANAGER` addressed to the assignee's manager — with
    `recipient_employee_id` left `null` when the employee has no manager."

    Design: Corner/rbac/manager_acknowledge_own_notice_and_others_forbidden
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(
        code="REG-ACK", name="ACK Regulator",
        escalation_interval_days=10, reminder_days_before_due=7,
    )
    cur = create_active_curriculum(reg["id"], code="CUR-ACK", title="ACK Course")
    mgr_role = create_role(code="R-ACKM", name="ACK Mgr Role")
    role = create_role(code="R-ACK", name="ACK Role")
    add_requirement(role["id"], cur["id"], due_in_days=2, criticality="SOFT")
    m1 = create_employee("M-ACK-1", mgr_role["id"], full_name="Ack Mgr One")
    m2 = create_employee("M-ACK-2", mgr_role["id"], full_name="Ack Mgr Two")
    emp = create_employee("E-ACK-1", role["id"], full_name="Ack Emp", manager_id=m1["id"])
    find_assignment(emp["id"], curriculum_id=cur["id"])

    set_clock("2026-08-06T09:00:00Z")  # one day past due -> OVERDUE
    sweep = run_sweep()
    assert sweep["notices_created"] == 1, "only the level-2 notice (DUE_SOON never swept)"

    notices, meta = list_employee_escalations(m1["id"])
    assert meta["total_count"] == 1
    note = notices[0]
    assert note["level"] == 2
    assert note["kind"] == "OVERDUE_MANAGER"
    assert note["recipient_employee_id"] == m1["id"], (
        "OVERDUE escalation addressed to the direct manager"
    )

    wrong_mgr = api.acknowledge_escalation(note["id"], make_manager_headers(m2["id"]))
    validate_error(wrong_mgr, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)

    ok = api.acknowledge_escalation(note["id"], make_manager_headers(m1["id"]))
    assert validate_success(ok, 200)["status"] == "ACKNOWLEDGED"

    again = api.acknowledge_escalation(note["id"], make_manager_headers(m1["id"]))
    validate_error(again, ApiErrorId.ERR_INVALID_STATE.value)
