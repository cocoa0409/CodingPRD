"""Non-linear lifecycles: the revision cycle that re-arms, the two incident
dimensions that move independently, and the claim fork that joins with divergent
effects (PRD §3.4, §3.5, §3.8)."""

from test_helpers import (
    assert_field,
    assert_posture,
    assert_state,
    close_claim,
    decide_task,
    escalate_claim_to_platform,
    filter_by,
    issue_correction,
    log_claim,
    read_channel,
    read_claim,
    read_incident,
    read_statement,
    read_task,
    refresh,
    seed_roster,
    set_clock,
    setup_activated_incident,
    setup_published_statement,
    setup_statement_in_review,
    submit_for_review,
    tasks_for_statement,
    triage_claim,
    validate_success,
    verify_channel_path,
)

# ---------------------------------------------------------------------------
# Statement: IN_REVIEW -> REVISION_REQUESTED -> DRAFT -> IN_REVIEW
# ---------------------------------------------------------------------------


def _statement_rejected_into_revision():
    """A SEV2 statement whose first review round was collapsed by the incident
    lead's REJECT, leaving the statement in REVISION_REQUESTED, the lead's task
    REJECTED and counsel's sibling task VOIDED."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PRODUCT_RECALL",
        title="Warehouse layoff rumours",
        seat_roles=["INCIDENT_LEAD", "LEGAL_COUNSEL"],
    )
    setup_statement_in_review(
        scenario,
        statement_type="HOLDING",
        body="We have no announcement about site staffing at this time.",
    )
    scenario["round_one"] = scenario["tasks"]
    scenario["lead_task"] = next(
        task for task in scenario["tasks"] if task["required_team_role"] == "INCIDENT_LEAD"
    )
    scenario["counsel_task"] = next(
        task for task in scenario["tasks"] if task["required_team_role"] == "LEGAL_COUNSEL"
    )
    decide_task(
        scenario["lead_task"], "REJECT", "Tighten the wording on staffing."
    )
    return scenario


def test_a_rejection_walks_the_statement_backwards_and_collapses_the_round(api):
    """PRD §3.5: "The task itself advances `PENDING → REJECTED` with `decided_at`
    stamped and the `decision_comment` stored, and the statement advances
    `IN_REVIEW → REVISION_REQUESTED` **immediately**, regardless of how many
    sibling tasks in the round have already been approved. ... Every sibling task
    of the same `revision_round` still in `PENDING` transitions to `VOIDED` with
    `decided_at` stamped. Because the round has collapsed,
    `open_approval_task_count` is recomputed back down to its pre-submission
    value."

    Design: Difficulty/non_linear_state_machine/nonlinear_statement_revision_cycle_returns_to_draft
    """
    scenario = _statement_rejected_into_revision()

    statement = read_statement(scenario["statement"]["id"])
    assert_state(statement, "REVISION_REQUESTED", "statement")
    assert_field(statement, "revision_round", 0, "statement")
    assert_field(statement, "revision_locked", False, "statement")

    lead_task = read_task(scenario["lead_task"]["id"])
    assert_state(lead_task, "REJECTED", "incident-lead task")
    assert_field(
        lead_task, "decision_comment", "Tighten the wording on staffing.", "incident-lead task"
    )
    assert lead_task["decided_at"] is not None, "a rejection must stamp decided_at"

    counsel_task = read_task(scenario["counsel_task"]["id"])
    assert_state(counsel_task, "VOIDED", "counsel task")
    assert counsel_task["decided_at"] is not None, "a voided sibling must stamp decided_at"
    assert_field(
        read_incident(scenario["incident"]["id"]), "open_approval_task_count", 0, "incident"
    )


def test_revising_and_resubmitting_re_arms_the_cycle_with_a_fresh_round(api):
    """PRD §3.5: "On success the statement returns `REVISION_REQUESTED → DRAFT`,
    `revision_round` increases by 1, `revision_locked` latches to true the moment
    `revision_round` reaches 3, `quorum_required` resets to 0 ... The full cycle
    is therefore `DRAFT → IN_REVIEW → REVISION_REQUESTED → DRAFT → IN_REVIEW` and
    so on, bounded at a `revision_round` of 3, and each new round re-derives the
    quorum from the tier and privilege flag as they stand at that moment and fans
    out a completely fresh set of approval tasks."

    Design: Difficulty/non_linear_state_machine/nonlinear_statement_revision_cycle_returns_to_draft
    """
    scenario = _statement_rejected_into_revision()

    revised = validate_success(
        api.revise_statement(
            scenario["statement"]["id"],
            {"body": "Staffing decisions have not been finalised; we will update by Friday."},
            scenario["headers"]["comms"],
        )
    )
    assert_state(revised, "DRAFT", "statement")
    assert_field(revised, "revision_round", 1, "statement")
    assert_field(revised, "revision_locked", False, "statement")
    assert_field(revised, "quorum_required", 0, "statement")

    resubmitted = submit_for_review(scenario)

    assert_state(resubmitted, "IN_REVIEW", "statement")
    assert_field(resubmitted, "revision_round", 1, "statement")
    assert_field(resubmitted, "revision_locked", False, "statement")
    assert_field(resubmitted, "quorum_required", 2, "statement")
    assert_field(resubmitted, "approvals_recorded", 0, "statement")

    tasks = tasks_for_statement(scenario["statement"]["id"])
    assert len(tasks) == 4, (
        "the collapsed round must be retained alongside the fresh one, got "
        f"{len(tasks)} tasks"
    )
    pending = filter_by(tasks, state="PENDING")
    assert len(pending) == 2, f"the fresh round must be fully pending, got {len(pending)}"
    for task in pending:
        assert_field(task, "revision_round", 1, "fresh task")
    assert_field(
        read_incident(scenario["incident"]["id"]), "open_approval_task_count", 2, "incident"
    )


# ---------------------------------------------------------------------------
# Incident: the privilege dimension moves while the response dimension holds
# ---------------------------------------------------------------------------


def _activated_incident_with_seated_counsel():
    """A SEV2 REGULATORY_PROBE incident in ACTIVATED, with the incident lead's
    seat and a privilege-cleared counsel's seat both ACKNOWLEDGED."""
    return setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="REGULATORY_PROBE",
        title="Subpoena reported by trade press",
        seat_roles=["INCIDENT_LEAD", "LEGAL_COUNSEL"],
    )


def test_asserting_privilege_freezes_the_posture_while_the_response_state_holds(api):
    """PRD §3.4: "`response_state` tracks the response itself, running
    `MONITORING → ACTIVATED → RESOLVED`. `privilege_state` tracks the legal
    posture, running `NON_PRIVILEGED → PRIVILEGED_ASSERTED → PRIVILEGE_WAIVED` ...
    neither privilege transition ever changes `response_state`, and neither
    response transition ever changes `privilege_state`", and "On success the
    incident advances `NON_PRIVILEGED → PRIVILEGED_ASSERTED`, `legal_hold_active`
    is set to true, the supplied `privilege_basis` is stored, and `comms_posture`
    recomputes to `FROZEN`".

    Design: Difficulty/non_linear_state_machine/nonlinear_incident_parallel_dimensions_move_independently
    """
    scenario = _activated_incident_with_seated_counsel()
    assert_field(scenario["incident"], "privilege_state", "NON_PRIVILEGED", "incident")
    version_before = scenario["incident"]["version"]

    asserted = validate_success(
        api.assert_privilege(
            scenario["incident"]["id"],
            {"privilege_basis": "Attorney work product prepared for outside counsel."},
            scenario["headers"]["counsel"],
        )
    )

    assert_field(asserted, "privilege_state", "PRIVILEGED_ASSERTED", "incident")
    assert_field(asserted, "legal_hold_active", True, "incident")
    assert_posture(asserted, "FROZEN")
    assert_field(asserted, "response_state", "ACTIVATED", "incident")
    assert_field(
        asserted,
        "privilege_basis",
        "Attorney work product prepared for outside counsel.",
        "incident",
    )
    assert asserted["version"] == version_before + 1, (
        "asserting privilege must increment the incident version by exactly 1, "
        f"got {version_before} then {asserted['version']}"
    )


def test_waiving_privilege_reopens_the_posture_and_still_leaves_the_response_state(api):
    """PRD §3.4: "The incident advances `PRIVILEGED_ASSERTED → PRIVILEGE_WAIVED`,
    `legal_hold_active` becomes false, and the posture is recomputed from scratch
    under the precedence of §2.6: it becomes `RESTRICTED` if `sla_breached` is true
    or `blocked_notice_count` is at least 1, `OPEN` if neither holds."

    The response dimension has stood still at `ACTIVATED` across both privilege
    hops, and with no breach and no blocked notice the posture returns to `OPEN`.

    Design: Difficulty/non_linear_state_machine/nonlinear_incident_parallel_dimensions_move_independently
    """
    scenario = _activated_incident_with_seated_counsel()
    validate_success(
        api.assert_privilege(
            scenario["incident"]["id"],
            {"privilege_basis": "Attorney work product prepared for outside counsel."},
            scenario["headers"]["counsel"],
        )
    )
    frozen = read_incident(scenario["incident"]["id"])
    assert_posture(frozen, "FROZEN")
    assert_field(frozen, "response_state", "ACTIVATED", "incident")

    waived = validate_success(
        api.waive_privilege(
            scenario["incident"]["id"],
            scenario["headers"]["counsel"],
            {"waiver_reason": "Counsel cleared the narrative for external use."},
        )
    )

    assert_field(waived, "privilege_state", "PRIVILEGE_WAIVED", "incident")
    assert_field(waived, "legal_hold_active", False, "incident")
    assert_posture(waived, "OPEN")
    assert_field(waived, "response_state", "ACTIVATED", "incident")
    assert_field(waived, "sla_breached", False, "incident")
    assert_field(waived, "blocked_notice_count", 0, "incident")
    assert waived["version"] == frozen["version"] + 1, (
        "waiving privilege must increment the incident version by exactly 1, "
        f"got {frozen['version']} then {waived['version']}"
    )


# ---------------------------------------------------------------------------
# MisinformationClaim: one fork out of TRIAGED, one join into CLOSED
# ---------------------------------------------------------------------------


def _two_triaged_claims_on_a_verified_channel():
    """A SEV2 incident carrying a PUBLISHED CORRECTION statement on a MEDIA
    channel whose escalation path is VERIFIED, plus two TRIAGED claims on that
    channel: claim P at virality 72.00 and claim C at 30.00."""
    set_clock("2026-08-10T09:00:00Z")
    roster = seed_roster()
    scenario = setup_activated_incident(
        tier="SEV2",
        scenario_code="PRODUCT_RECALL",
        title="Fabricated recall notice circulating",
        roster=roster,
    )
    verify_channel_path(
        scenario["channel"]["id"],
        verified_contact_reference="trust-and-safety@wire.example",
    )
    setup_published_statement(
        scenario,
        statement_type="CORRECTION",
        body="No recall has been issued; the circulating notice is fabricated.",
    )
    scenario["claim_p"] = log_claim(
        scenario,
        virality_score=72.00,
        claim_text="Recall covers all units sold since 2024.",
    )
    scenario["claim_c"] = log_claim(
        scenario,
        virality_score=30.00,
        claim_text="Refunds are being processed automatically.",
    )
    triage_claim(scenario, claim_id=scenario["claim_p"]["id"])
    triage_claim(scenario, claim_id=scenario["claim_c"]["id"])
    for key in ("claim_p", "claim_c"):
        scenario[key] = read_claim(scenario[key]["id"])
        assert_state(scenario[key], "TRIAGED", key)
    return scenario


def test_the_fork_sends_two_identically_triaged_claims_down_different_branches(api):
    """PRD §3.8: "From `TRIAGED` the claim forks, and the two branches are
    genuinely different responses rather than variants of one." The platform
    branch advances `TRIAGED → PLATFORM_ESCALATED` and "On success the channel's
    `open_escalation_count` is recomputed"; the correction branch advances
    `TRIAGED → CORRECTION_ISSUED` where "`correction_window_minutes` is derived as
    the whole number of complete minutes between the window's start and end with
    any remainder discarded, the channel's `reserved_correction_minutes` increases
    by exactly that many minutes".

    Neither branch writes `resolution_branch` yet — that is "written only when the
    claim closes" — so at the fork the two claims are distinguishable only by
    state and by which channel ledger they moved.

    Design: Difficulty/non_linear_state_machine/nonlinear_claim_fork_join_divergent_close_effects
    """
    scenario = _two_triaged_claims_on_a_verified_channel()

    platform = escalate_claim_to_platform(scenario, claim_id=scenario["claim_p"]["id"])
    correction = issue_correction(
        scenario,
        "2026-08-10T11:00:00Z",
        "2026-08-10T11:30:00Z",
        claim_id=scenario["claim_c"]["id"],
    )

    assert_state(platform, "PLATFORM_ESCALATED", "claim P")
    assert_field(platform, "resolution_branch", None, "claim P")
    assert_state(correction, "CORRECTION_ISSUED", "claim C")
    assert_field(correction, "resolution_branch", None, "claim C")
    assert_field(correction, "correction_window_minutes", 30, "claim C")
    assert_field(
        correction, "correction_statement_id", scenario["statement"]["id"], "claim C"
    )

    channel = read_channel(scenario["channel"]["id"])
    assert_field(channel, "open_escalation_count", 1, "channel")
    assert_field(channel, "reserved_correction_minutes", 30, "channel")
    assert_field(refresh(scenario), "open_claim_count", 2, "incident")


def test_the_two_branches_join_in_closed_with_divergent_side_effects(api):
    """PRD §3.8: "Closing from `PLATFORM_ESCALATED` sets `resolution_branch` to
    `PLATFORM`, sets `takedown_confirmed` to true, leaves `corrected` false,
    recomputes the channel's `open_escalation_count` ... Closing from
    `CORRECTION_ISSUED` sets `resolution_branch` to `CORRECTION`, sets `corrected`
    to true ... leaves `takedown_confirmed` false, and compensates the airtime
    ledger by decreasing the channel's `reserved_correction_minutes` by exactly
    this claim's `correction_window_minutes`, restoring it to its pre-correction
    value ... Both branches then recompute the incident's `open_claim_count`."

    Design: Difficulty/non_linear_state_machine/nonlinear_claim_fork_join_divergent_close_effects
    """
    scenario = _two_triaged_claims_on_a_verified_channel()
    escalate_claim_to_platform(scenario, claim_id=scenario["claim_p"]["id"])
    issue_correction(
        scenario,
        "2026-08-10T11:00:00Z",
        "2026-08-10T11:30:00Z",
        claim_id=scenario["claim_c"]["id"],
    )

    closed_platform = close_claim(
        scenario,
        claim_id=scenario["claim_p"]["id"],
        actor="listener",
        outcome_note="Platform removed the post.",
    )
    closed_correction = close_claim(
        scenario,
        claim_id=scenario["claim_c"]["id"],
        actor="comms",
        outcome_note="Correction pinned above the thread.",
    )

    assert_state(closed_platform, "CLOSED", "claim P")
    assert_field(closed_platform, "resolution_branch", "PLATFORM", "claim P")
    assert_field(closed_platform, "takedown_confirmed", True, "claim P")
    assert_field(closed_platform, "corrected", False, "claim P")
    assert_field(
        closed_platform, "outcome_note", "Platform removed the post.", "claim P"
    )

    assert_state(closed_correction, "CLOSED", "claim C")
    assert_field(closed_correction, "resolution_branch", "CORRECTION", "claim C")
    assert_field(closed_correction, "corrected", True, "claim C")
    assert_field(closed_correction, "takedown_confirmed", False, "claim C")

    channel = read_channel(scenario["channel"]["id"])
    assert_field(channel, "open_escalation_count", 0, "channel")
    assert_field(channel, "reserved_correction_minutes", 0, "channel")
    assert_field(refresh(scenario), "open_claim_count", 0, "incident")
