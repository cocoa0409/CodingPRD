"""Transitive cascades: one request, then a chain of consequences where each hop
is caused by the hop before it rather than by the caller (PRD §3.3, §3.4, §3.5,
§3.6, §3.7, §3.9)."""

from test_helpers import (
    assert_containment,
    assert_field,
    assert_posture,
    assert_severity,
    assert_privilege,
    assert_state,
    assert_two_decimals,
    book_interview,
    confirm_interview,
    decide_task,
    draft_statement,
    escalate_signal,
    link_signal,
    queue_notice,
    read_assignment,
    read_incident,
    read_interview,
    read_member,
    read_notice,
    read_signal,
    read_statement,
    read_task,
    record_signal,
    refresh,
    resolve_incident,
    set_clock,
    setup_activated_incident,
    setup_statement_in_review,
    submit_for_review,
    tasks_for_statement,
)

# ---------------------------------------------------------------------------
# Reject -> void sibling -> block notice -> restrict posture
# ---------------------------------------------------------------------------


def _statement_in_review_with_a_queued_notice():
    """A SEV2 incident whose INCIDENT_LEAD and LEGAL_COUNSEL seats are both
    ACKNOWLEDGED, carrying one HOLDING statement `IN_REVIEW` with two PENDING
    tasks and one QUEUED EMPLOYEE notice that names that statement."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PRODUCT_RECALL",
        title="Contaminated batch allegation",
        seat_roles=["INCIDENT_LEAD", "LEGAL_COUNSEL"],
    )
    draft_statement(
        scenario,
        statement_type="HOLDING",
        body="We are testing the retained samples and will report findings.",
    )
    queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1000)
    submit_for_review(scenario)
    scenario["lead_task"] = next(
        task for task in scenario["tasks"] if task["required_team_role"] == "INCIDENT_LEAD"
    )
    scenario["counsel_task"] = next(
        task for task in scenario["tasks"] if task["required_team_role"] == "LEGAL_COUNSEL"
    )
    incident = refresh(scenario)
    assert_field(incident, "open_approval_task_count", 2, "incident")
    assert_field(incident, "blocked_notice_count", 0, "incident")
    assert_posture(incident, "OPEN")
    assert_state(scenario["notices"]["EMPLOYEE"], "QUEUED", "employee notice")
    return scenario


def test_one_rejection_voids_the_untouched_sibling_and_reverses_the_statement(api):
    """PRD §3.5: "The task itself advances `PENDING → REJECTED` with `decided_at`
    stamped and the `decision_comment` stored, and the statement advances
    `IN_REVIEW → REVISION_REQUESTED` **immediately** ... Every sibling task of the
    same `revision_round` still in `PENDING` transitions to `VOIDED` with
    `decided_at` stamped. Because the round has collapsed,
    `open_approval_task_count` is recomputed back down to its pre-submission
    value."

    Counsel is never asked anything here: the void on their task is caused by the
    lead's rejection, not by any request of their own.

    Design: Difficulty/transitive_cascade/cascade_reject_voids_sibling_blocks_notice_and_restricts_posture
    """
    scenario = _statement_in_review_with_a_queued_notice()

    decide_task(
        scenario["lead_task"], "REJECT", "Do not confirm testing before counsel reviews."
    )

    lead_task = read_task(scenario["lead_task"]["id"])
    assert_state(lead_task, "REJECTED", "incident-lead task")
    assert_field(
        lead_task,
        "decision_comment",
        "Do not confirm testing before counsel reviews.",
        "incident-lead task",
    )
    assert lead_task["decided_at"] is not None, "a rejection must stamp decided_at"

    counsel_task = read_task(scenario["counsel_task"]["id"])
    assert_state(counsel_task, "VOIDED", "counsel task")
    assert counsel_task["decided_at"] is not None, "a voided sibling must stamp decided_at"

    assert_state(
        read_statement(scenario["statement"]["id"]), "REVISION_REQUESTED", "statement"
    )
    assert tasks_for_statement(scenario["statement"]["id"], state="PENDING") == [], (
        "the collapsed round may leave no pending task behind"
    )
    assert_field(refresh(scenario), "open_approval_task_count", 0, "incident")


def test_the_collapsed_round_blocks_the_notice_and_restricts_the_posture(api):
    """PRD §3.5: "Because the statement is no longer approvable, every stakeholder
    notice carrying it that sits in `QUEUED` transitions to `BLOCKED`, and
    `blocked_notice_count` is recomputed. And because `blocked_notice_count` has
    become at least 1, `comms_posture` recomputes to `RESTRICTED`, unless
    `legal_hold_active` is forcing `FROZEN`. The incident's `version` is
    incremented by 1."

    PRD §2.6 confirms which rule is matching: the posture "is `RESTRICTED` when
    `sla_breached` is true, or when `blocked_notice_count` is at least 1" — and
    with no legal hold in force nothing outranks it.  The notice itself was never
    addressed by the request, and the response dimension has not moved.

    Design: Difficulty/transitive_cascade/cascade_reject_voids_sibling_blocks_notice_and_restricts_posture
    """
    scenario = _statement_in_review_with_a_queued_notice()
    notice_id = scenario["notices"]["EMPLOYEE"]["id"]
    version_before = read_incident(scenario["incident"]["id"])["version"]

    decide_task(
        scenario["lead_task"], "REJECT", "Do not confirm testing before counsel reviews."
    )

    notice = read_notice(notice_id)
    assert_state(notice, "BLOCKED", "employee notice")
    assert notice["released_at"] is None, "a blocked notice was never released"
    assert notice["cancel_reason"] is None, "blocking is not cancelling"
    incident = refresh(scenario)
    assert_field(incident, "blocked_notice_count", 1, "incident")
    assert_posture(incident, "RESTRICTED")
    assert_field(incident, "legal_hold_active", False, "incident")
    assert_field(incident, "sla_breached", False, "incident")
    assert_field(incident, "response_state", "ACTIVATED", "incident")
    assert incident["version"] == version_before + 1, (
        "the rejection cascade must increment the incident version by exactly 1, "
        f"got {version_before} then {incident['version']}"
    )


# ---------------------------------------------------------------------------
# Resolve -> stand the seats down -> cancel the interview -> release the minutes
# ---------------------------------------------------------------------------


def _resolvable_incident_with_a_confirmed_interview():
    """A SEV2 incident with ACKNOWLEDGED INCIDENT_LEAD and SPOKESPERSON seats and
    one CONFIRMED sixty-minute interview, carrying no queued notices and no open
    claims so resolution is permitted."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PLANT_INCIDENT",
        title="Overnight release at the north plant",
        seat_roles=["INCIDENT_LEAD", "SPOKESPERSON"],
    )
    book_interview(
        scenario,
        "2026-08-10T14:00:00Z",
        "2026-08-10T15:00:00Z",
        anticipated_question_count=8,
        outlet_name="National Wire Evening",
    )
    confirm_interview(scenario, high_risk_answers_approved_count=3)
    assert_field(scenario["interview"], "duration_minutes", 60, "interview")
    assert_field(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 60,
        "spokesperson",
    )
    assert_field(refresh(scenario), "confirmed_interview_count", 1, "incident")
    return scenario


def test_resolution_stands_every_acknowledged_seat_down(api):
    """PRD §3.9: "every crisis-team seat on this incident in state `ACKNOWLEDGED`
    transitions `ACKNOWLEDGED → STOOD_DOWN` with `stood_down_at` stamped at the
    current instant, and each affected member's `active_assignment_count` is
    recomputed."

    PRD §2.2 fixes what that counter means — it is "the number of crisis-team seats
    held by that member in state `ASSIGNED` or `ACKNOWLEDGED`" — so standing the
    seats down empties it for both people.

    Design: Difficulty/transitive_cascade/cascade_resolve_stands_down_seat_cancels_interview_releases_minutes
    """
    scenario = _resolvable_incident_with_a_confirmed_interview()
    lead_seat_id = scenario["assignments"]["INCIDENT_LEAD"]["id"]
    spox_seat_id = scenario["assignments"]["SPOKESPERSON"]["id"]

    resolved = resolve_incident(scenario, reputation_index_after=48.00)

    assert_field(resolved, "response_state", "RESOLVED", "incident")
    for label, seat_id in (("incident-lead seat", lead_seat_id), ("spokesperson seat", spox_seat_id)):
        seat = read_assignment(seat_id)
        assert_state(seat, "STOOD_DOWN", label)
        assert seat["stood_down_at"] is not None, f"{label} must stamp stood_down_at"
        assert seat["stood_down_at"].startswith("2026-08-10T09:00:00"), (
            f"{label} must stand down at the current instant, got {seat['stood_down_at']}"
        )
    assert_field(
        read_member(scenario["ids"]["lead"]), "active_assignment_count", 0, "incident lead"
    )
    assert_field(
        read_member(scenario["ids"]["spox"]), "active_assignment_count", 0, "spokesperson"
    )


def test_the_stood_down_seat_cancels_the_interview_and_frees_the_minutes(api):
    """PRD §3.9: "because the `SPOKESPERSON` seat has stood down, every interview
    on this incident whose `spokesperson_member_id` is that seat's member and which
    sits in `SCHEDULED` or `CONFIRMED` transitions to `CANCELLED` with
    `cancel_reason` set to the literal string `AUTO_CASCADE_INCIDENT_RESOLVED`.
    Third, because those interviews have left `CONFIRMED`, that spokesperson's
    `scheduled_interview_minutes` is decreased by each cancelled interview's
    `duration_minutes`, and the incident's `confirmed_interview_count` is
    recomputed. Finally `comms_posture` recomputes to `FROZEN` ... and the
    incident's `version` is incremented by 1."

    Nobody cancelled this booking and nobody named the spokesperson: the whole
    chain hangs off resolving the incident.

    Design: Difficulty/transitive_cascade/cascade_resolve_stands_down_seat_cancels_interview_releases_minutes
    """
    scenario = _resolvable_incident_with_a_confirmed_interview()
    interview_id = scenario["interview"]["id"]
    version_before = read_incident(scenario["incident"]["id"])["version"]

    resolved = resolve_incident(scenario, reputation_index_after=48.00)

    interview = read_interview(interview_id)
    assert_state(interview, "CANCELLED", "interview")
    assert_field(
        interview, "cancel_reason", "AUTO_CASCADE_INCIDENT_RESOLVED", "interview"
    )
    assert_field(interview, "duration_minutes", 60, "interview")
    assert_field(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 0,
        "spokesperson",
    )
    assert_field(resolved, "confirmed_interview_count", 0, "incident")
    assert_posture(resolved, "FROZEN")
    assert resolved["version"] == version_before + 1, (
        "the resolution cascade must increment the incident version by exactly 1, "
        f"got {version_before} then {resolved['version']}"
    )


# ---------------------------------------------------------------------------
# Escalate -> raise the tier -> shorten the deadline retroactively -> restrict
# ---------------------------------------------------------------------------


def _activated_sev2_carrying_a_stronger_linked_signal():
    """A SEV2 incident activated at 09:00 — deadline 10:00, no breach — with a
    second MEDIA signal scoring 96.00 merely LINKED, and the clock moved on to
    09:45 without any holding statement having been published."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="EXEC_MISCONDUCT",
        title="Boardroom departure speculation",
        seat_roles=["INCIDENT_LEAD"],
    )
    incident = scenario["incident"]
    assert_severity(incident, "SEV2", 83.00, "PROVISIONAL")
    assert incident["holding_statement_due_at"].startswith("2026-08-10T10:00:00"), (
        "the SEV2 window must put the deadline at 10:00, got "
        f"{incident['holding_statement_due_at']}"
    )
    scenario["second_signal"] = record_signal(
        scenario["channel"]["id"],
        scenario["headers"]["listener"],
        headline="Network confirms an on-air interview with the source",
        reach_score=88,
    )
    link_signal(
        scenario["second_signal"]["id"],
        incident["id"],
        scenario["headers"]["listener"],
    )
    set_clock("2026-08-10T09:45:00Z")
    waiting = refresh(scenario)
    assert_field(waiting, "linked_signal_count", 2, "incident")
    assert_field(waiting, "escalated_signal_count", 1, "incident")
    assert_field(waiting, "sla_breached", False, "incident")
    assert_field(waiting, "holding_statement_published_at", None, "incident")
    assert_posture(waiting, "OPEN")
    return scenario


def test_escalating_the_stronger_signal_moves_the_deadline_backwards(api):
    """PRD §3.3: "First, `severity_tier`, `severity_score` and the `PROVISIONAL`
    basis are recomputed from the enlarged candidate set ... Second, because the
    tier may have changed, `holding_statement_due_at` is recomputed as
    `activated_at` plus the new tier's window", and the base instant is pinned:
    "`activated_at` is the **only** base instant this deadline is ever computed
    from. When the tier tightens later in the response, the window shortens
    retroactively; the deadline is never re-based on the instant of the escalation
    that changed the tier."

    The escalation happens at 09:45, so a deadline re-based on the request would
    read 10:15; re-based on `activated_at` under the new SEV1 half-hour window it
    reads 09:30 — a deadline already in the past.

    Design: Difficulty/transitive_cascade/cascade_escalation_reshortens_sla_and_latches_breach
    """
    scenario = _activated_sev2_carrying_a_stronger_linked_signal()

    escalated = escalate_signal(
        scenario["second_signal"]["id"], scenario["headers"]["listener"]
    )

    assert_state(escalated, "ESCALATED", "second signal")
    assert_two_decimals(escalated["escalation_score"], 96.00, "escalation_score")
    incident = refresh(scenario)
    assert_severity(incident, "SEV1", 96.00, "PROVISIONAL")
    assert incident["holding_statement_due_at"].startswith("2026-08-10T09:30:00"), (
        "the tightened window must re-base on activated_at, giving 09:30, got "
        f"{incident['holding_statement_due_at']}"
    )
    assert incident["activated_at"].startswith("2026-08-10T09:00:00"), (
        f"activated_at must still read 09:00, got {incident['activated_at']}"
    )
    assert_field(incident, "escalated_signal_count", 2, "incident")
    assert_state(read_signal(scenario["signal"]["id"]), "ESCALATED", "first signal")


def test_the_retroactive_deadline_latches_the_breach_and_restricts_the_posture(api):
    """PRD §3.3: "Third, because the deadline may have moved earlier, the breach
    test is re-evaluated: if the current instant now sits at or past the new
    `holding_statement_due_at` and `holding_statement_published_at` is still null,
    `sla_breached` latches true. Fourth, because `sla_breached` just became true,
    `comms_posture` recomputes to `RESTRICTED` ... The containment family is
    recomputed as well, and the incident's `version` is incremented by 1."

    The 09:45 clock was comfortably inside the old 10:00 deadline; it is past the
    new 09:30 one, so the incident falls into breach without the clock having moved
    at all.  The containment family follows the new tier: seven tenths of the SEV1
    point value of 100 plus three tenths of a zero exposure gives a base of 70.00,
    which bands `MEDIUM` at the 0.10 rate for a total of 77.00.

    Design: Difficulty/transitive_cascade/cascade_escalation_reshortens_sla_and_latches_breach
    """
    scenario = _activated_sev2_carrying_a_stronger_linked_signal()
    version_before = read_incident(scenario["incident"]["id"])["version"]

    escalate_signal(scenario["second_signal"]["id"], scenario["headers"]["listener"])

    incident = refresh(scenario)
    assert_field(incident, "sla_breached", True, "incident")
    assert_field(incident, "holding_statement_published_at", None, "incident")
    assert_posture(incident, "RESTRICTED")
    assert_field(incident, "legal_hold_active", False, "incident")
    assert_field(incident, "blocked_notice_count", 0, "incident")
    assert_containment(incident, 70.00, 0.10, 77.00)
    assert incident["version"] == version_before + 1, (
        "the escalation cascade must increment the incident version by exactly 1, "
        f"got {version_before} then {incident['version']}"
    )


# ---------------------------------------------------------------------------
# Assert privilege -> void the uncleared approver -> reopen the revision loop
# ---------------------------------------------------------------------------


def _statement_in_review_with_only_counsel_approved():
    """A SEV2 statement `IN_REVIEW` on a quorum of 2 whose LEGAL_COUNSEL task is
    already APPROVED, leaving exactly one PENDING task held by the incident lead —
    a member whose `privilege_cleared` is false."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="REGULATORY_PROBE",
        title="Whistleblower letter to the regulator",
        seat_roles=["INCIDENT_LEAD", "LEGAL_COUNSEL"],
    )
    setup_statement_in_review(
        scenario,
        statement_type="HOLDING",
        body="We received the correspondence and are reviewing it.",
    )
    scenario["lead_task"] = next(
        task for task in scenario["tasks"] if task["required_team_role"] == "INCIDENT_LEAD"
    )
    scenario["counsel_task"] = next(
        task for task in scenario["tasks"] if task["required_team_role"] == "LEGAL_COUNSEL"
    )
    assert_field(
        read_member(scenario["ids"]["lead"]), "privilege_cleared", False, "incident lead"
    )
    assert_field(
        read_member(scenario["ids"]["counsel"]), "privilege_cleared", True, "counsel"
    )
    decide_task(scenario["counsel_task"], "APPROVE", "Language is acceptable to counsel.")
    statement = read_statement(scenario["statement"]["id"])
    assert_state(statement, "IN_REVIEW", "statement")
    assert_field(statement, "quorum_required", 2, "statement")
    assert_field(statement, "approvals_recorded", 1, "statement")
    assert_field(refresh(scenario), "open_approval_task_count", 1, "incident")
    return scenario


def test_asserting_privilege_voids_the_pending_task_of_the_uncleared_approver(api):
    """PRD §3.4: "every approval task on this incident's statements that is still
    `PENDING` and whose assignee has `privilege_cleared` false transitions to
    `VOIDED` with `decided_at` stamped at the current instant; approvers outside
    the circle lose their pending decisions outright. Second, because those tasks
    were voided, `open_approval_task_count` is recomputed."

    The lead was never asked to decide and never touched the statement: the loss of
    their pending task is caused entirely by counsel drawing the privilege circle,
    and the already-recorded approval inside the circle survives untouched.

    Design: Difficulty/transitive_cascade/cascade_privilege_assertion_voids_uncleared_approver_and_reopens_revision
    """
    scenario = _statement_in_review_with_only_counsel_approved()

    incident = assert_privilege(
        scenario,
        privilege_basis="Response strategy prepared at the direction of counsel.",
    )

    assert_field(incident, "privilege_state", "PRIVILEGED_ASSERTED", "incident")
    assert_field(incident, "legal_hold_active", True, "incident")
    assert_posture(incident, "FROZEN")

    lead_task = read_task(scenario["lead_task"]["id"])
    assert_state(lead_task, "VOIDED", "incident-lead task")
    assert lead_task["decided_at"] is not None, "a voided task must stamp decided_at"
    assert lead_task["decided_at"].startswith("2026-08-10T09:00:00"), (
        f"the void must be stamped at the current instant, got {lead_task['decided_at']}"
    )
    assert_state(read_task(scenario["counsel_task"]["id"]), "APPROVED", "counsel task")
    assert_field(incident, "open_approval_task_count", 0, "incident")


def test_the_emptied_round_pushes_the_statement_back_into_revision(api):
    """PRD §3.4: "Third, because a statement in `IN_REVIEW` can lose every one of
    its outstanding tasks this way, any such statement that is left with zero
    remaining `PENDING` tasks and fewer `APPROVED` tasks than its
    `quorum_required` transitions to `REVISION_REQUESTED`. The incident's `version`
    is incremented by 1."

    One approval out of a quorum of two is what makes this hop fire: the round has
    nothing left to decide and cannot reach its quorum, so the message goes back for
    redrafting even though nobody rejected it.

    Design: Difficulty/transitive_cascade/cascade_privilege_assertion_voids_uncleared_approver_and_reopens_revision
    """
    scenario = _statement_in_review_with_only_counsel_approved()
    version_before = read_incident(scenario["incident"]["id"])["version"]

    assert_privilege(
        scenario,
        privilege_basis="Response strategy prepared at the direction of counsel.",
    )

    statement = read_statement(scenario["statement"]["id"])
    assert_state(statement, "REVISION_REQUESTED", "statement")
    assert_field(statement, "quorum_required", 2, "statement")
    assert_field(statement, "approvals_recorded", 1, "statement")
    assert_field(statement, "revision_round", 0, "statement")
    assert statement["approved_at"] is None, (
        "a statement that never reached quorum must not stamp approved_at"
    )
    assert tasks_for_statement(scenario["statement"]["id"], state="PENDING") == [], (
        "the emptied round may leave no pending task behind"
    )
    incident = refresh(scenario)
    assert_field(incident, "response_state", "ACTIVATED", "incident")
    assert incident["version"] == version_before + 1, (
        "the privilege cascade must increment the incident version by exactly 1, "
        f"got {version_before} then {incident['version']}"
    )
