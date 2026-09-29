"""Overdue escalation: the chase ladder alongside a frozen acknowledgment state."""
from test_helpers import (
    api_client,
    assert_same_instant,
    make_admin_headers,
    refresh_assignment,
    refresh_case,
    refresh_employee,
    setup_open_escalation_case,
    validate_success,
)


def test_escalation_dimension_walks_to_resolved_while_ack_state_stays_pending():
    """PRD §3.8: "supplying an `outcome` of `DISCIPLINARY` moves the case
    `ESCALATED_HR → CLOSED_DISCIPLINARY` with `closed_at` stamped from the logical
    clock, requires the case to be in `ESCALATED_HR` and the linked assignment's
    `ack_state` to still be `PENDING`, sets the assignment's `escalation_state` to
    `RESOLVED`, decrements the subject's `open_escalation_count` by 1 ... Notably
    the assignment is **left** at `PENDING` and the subject's `open_ack_count` is
    untouched: discipline does not discharge the obligation to acknowledge".

    Design: Difficulty/non_linear_state_machine/assignment_escalation_dimension_advances_while_ack_dimension_frozen
    """
    ctx = setup_open_escalation_case(document={"max_ack_deadline_days": 5})
    case, assignment, employee = ctx["case"], ctx["assignment"], ctx["employee"]
    assert case["status"] == "OPEN"
    assert case["tier"] == 3, (
        f"14 whole days overdue is already base tier 3, got {case['tier']}"
    )
    assert case["notified_manager_id"] == ctx["manager"]["id"], (
        "the case must record the subject's manager at open time, got "
        f"{case['notified_manager_id']}"
    )

    notified = validate_success(
        api_client.notify_escalation(case["id"], make_admin_headers())
    )
    assert notified["status"] == "NOTIFIED", (
        f"OPEN -> NOTIFIED expected, got {notified['status']}"
    )
    assert notified["notice_count"] == 1, (
        f"notifying must raise notice_count to 1, got {notified['notice_count']}"
    )

    escalated = validate_success(
        api_client.escalate_hr(case["id"], make_admin_headers())
    )
    assert escalated["status"] == "ESCALATED_HR", (
        f"NOTIFIED -> ESCALATED_HR expected at tier 3, got {escalated['status']}"
    )

    mid_chase = refresh_assignment(assignment["id"])
    assert mid_chase["ack_state"] == "PENDING", (
        "the acknowledgment dimension must not move while the chase advances, got "
        f"{mid_chase['ack_state']}"
    )
    assert mid_chase["escalation_state"] == "ESCALATING", (
        f"the escalation dimension must sit at ESCALATING, got {mid_chase['escalation_state']}"
    )

    closed = validate_success(
        api_client.close_escalation(
            case["id"], {"outcome": "DISCIPLINARY"}, make_admin_headers()
        )
    )
    assert closed["status"] == "CLOSED_DISCIPLINARY", (
        f"ESCALATED_HR -> CLOSED_DISCIPLINARY expected, got {closed['status']}"
    )
    assert closed["tier"] == 3, (
        f"a closed case is not re-tiered, so tier stays 3, got {closed['tier']}"
    )
    assert_same_instant(closed["closed_at"], "2026-09-03T00:00:00Z", "closed_at")

    final = refresh_assignment(assignment["id"])
    assert final["escalation_state"] == "RESOLVED", (
        f"the disciplinary close resolves the chase, got {final['escalation_state']}"
    )
    assert final["ack_state"] == "PENDING", (
        "discipline does not discharge the acknowledgment obligation, got "
        f"{final['ack_state']}"
    )
    assert final["days_overdue"] == 14, (
        f"the overdue count is unaffected by the chase, got {final['days_overdue']}"
    )
    assert_same_instant(final["due_date"], "2026-08-20T00:00:00Z", "due_date")

    subject = refresh_employee(employee["id"])
    assert subject["open_escalation_count"] == 0, (
        f"the closed case releases the escalation counter, got {subject['open_escalation_count']}"
    )
    assert subject["open_ack_count"] == 1, (
        "open_ack_count is untouched by the disciplinary close, got "
        f"{subject['open_ack_count']}"
    )


def test_acknowledging_after_a_disciplinary_close_moves_only_the_ack_dimension():
    """PRD §3.7: "A row may legitimately be `PENDING` on one axis and `ESCALATING`
    on the other, or `ACKNOWLEDGED` and `RESOLVED`; an acknowledgment-dimension move
    never writes the escalation dimension except through the cross-dimension side
    effects documented explicitly here and in §3.8." ... "Hop 4: ... any escalation
    case on this assignment whose `status` is `OPEN`, `NOTIFIED` or `ESCALATED_HR` is
    closed as `CLOSED_ACKNOWLEDGED`".

    Design: Difficulty/non_linear_state_machine/assignment_escalation_dimension_advances_while_ack_dimension_frozen
    """
    from test_helpers import acknowledge

    ctx = setup_open_escalation_case(document={"max_ack_deadline_days": 5})
    case, employee = ctx["case"], ctx["employee"]
    validate_success(api_client.notify_escalation(case["id"], make_admin_headers()))
    validate_success(api_client.escalate_hr(case["id"], make_admin_headers()))
    validate_success(
        api_client.close_escalation(
            case["id"], {"outcome": "DISCIPLINARY"}, make_admin_headers()
        )
    )
    assert refresh_employee(employee["id"])["open_escalation_count"] == 0

    acknowledged = acknowledge(
        refresh_assignment(ctx["assignment"]["id"]), employee["id"]
    )
    assert acknowledged["status"] == "EFFECTIVE"

    row = refresh_assignment(ctx["assignment"]["id"])
    assert row["ack_state"] == "ACKNOWLEDGED", (
        "the still-PENDING obligation can be discharged after the chase closed, got "
        f"{row['ack_state']}"
    )
    assert row["escalation_state"] == "RESOLVED", (
        "the escalation dimension was already RESOLVED and must not move again, got "
        f"{row['escalation_state']}"
    )
    assert_same_instant(row["acknowledged_at"], "2026-09-03T00:00:00Z", "acknowledged_at")

    assert refresh_case(case["id"])["status"] == "CLOSED_DISCIPLINARY", (
        "a case already closed as disciplinary is outside hop 4's from-state set and "
        "must not be re-closed as CLOSED_ACKNOWLEDGED"
    )
    subject = refresh_employee(employee["id"])
    assert subject["open_escalation_count"] == 0, (
        "hop 4 must not decrement an already-released escalation counter, got "
        f"{subject['open_escalation_count']}"
    )
    assert subject["open_ack_count"] == 0, (
        f"the acknowledgment releases the open obligation, got {subject['open_ack_count']}"
    )
