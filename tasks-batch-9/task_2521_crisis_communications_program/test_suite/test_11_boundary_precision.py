"""Inclusive-boundary arithmetic: the escalation threshold, the readiness floor
and the review deadline (PRD §3.1, §3.2, §3.5)."""

from test_helpers import (
    ApiErrorId,
    assert_field,
    assert_no_write,
    assert_state,
    assert_two_decimals,
    file_material,
    link_signal,
    open_incident,
    read_incident,
    read_material,
    read_signal,
    read_statement,
    read_task,
    record_signal,
    refresh,
    register_channel,
    review_material,
    run_sla_sweep,
    seed_roster,
    set_clock,
    setup_activated_incident,
    submit_for_review,
    draft_statement,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# The escalation threshold: exactly 70.00 passes
# ---------------------------------------------------------------------------


def _two_linked_signals_astride_the_threshold():
    """A MONITORING incident carrying one signal scoring exactly 70.00 (reach 62
    on a MEDIA surface) and one scoring 69.00 (reach 61), both LINKED."""
    set_clock("2026-08-10T09:00:00Z")
    scenario = seed_roster()
    channel = register_channel(name="National Wire", channel_type="MEDIA")
    incident = open_incident(
        scenario["headers"]["lead"],
        title="Packaging complaint cluster",
        scenario_code="PRODUCT_RECALL",
    )
    listener = scenario["headers"]["listener"]
    at_threshold = record_signal(
        channel["id"],
        listener,
        headline="Consumer column picks up the complaints",
        reach_score=62,
    )
    below = record_signal(
        channel["id"],
        listener,
        headline="Regional blog repeats the column",
        reach_score=61,
    )
    link_signal(at_threshold["id"], incident["id"], listener)
    link_signal(below["id"], incident["id"], listener)
    scenario["channel"] = channel
    scenario["incident"] = incident
    return scenario, at_threshold, below


def test_a_score_of_exactly_seventy_escalates(api):
    """PRD §3.2: "A signal advances `LINKED → ESCALATED` only when its frozen
    `escalation_score` is at least 70.00; a score of exactly 70.00 passes and
    69.99 does not."

    Reach 62 at tier A on a MEDIA surface freezes at 62.00 + 8 = 70.00, exactly
    the inclusive floor.

    Design: Difficulty/boundary_precision_check/boundary_escalation_score_at_exactly_seventy_on_escalate
    """
    scenario, at_threshold, _ = _two_linked_signals_astride_the_threshold()

    escalated = validate_success(
        api.escalate_issue_signal(at_threshold["id"], scenario["headers"]["listener"])
    )

    assert_two_decimals(escalated["escalation_score"], 70.00, "escalation_score")
    assert_state(escalated, "ESCALATED", "signal at the threshold")
    assert escalated["escalated_at"] is not None, "escalated_at must be stamped"
    assert_field(refresh(scenario), "escalated_signal_count", 1, "incident")


def test_a_score_one_point_below_the_threshold_is_refused(api):
    """PRD §3.2: "a score below the threshold is refused with
    `ERR_ESCALATION_THRESHOLD_NOT_MET` (HTTP 422)."

    Reach 61 at tier A on a MEDIA surface freezes at 69.00, one point short, and
    the signal must stay LINKED.

    Design: Difficulty/boundary_precision_check/boundary_escalation_score_at_exactly_seventy_on_escalate
    """
    scenario, _, below = _two_linked_signals_astride_the_threshold()
    before = read_signal(below["id"])

    validate_error(
        api.escalate_issue_signal(below["id"], scenario["headers"]["listener"]),
        ApiErrorId.ERR_ESCALATION_THRESHOLD_NOT_MET,
        422,
    )

    after = read_signal(below["id"])
    assert_two_decimals(after["escalation_score"], 69.00, "escalation_score")
    assert_state(after, "LINKED", "signal below the threshold")
    assert_no_write(before, after, "signal below the threshold")
    assert_field(refresh(scenario), "escalated_signal_count", 0, "incident")


# ---------------------------------------------------------------------------
# The readiness floor: exactly 60.00 is still READY
# ---------------------------------------------------------------------------


def _reviewed_faq_and_matching_incident():
    """A DATA_BREACH incident plus a DATA_BREACH FAQ reviewed at
    2026-08-01T00:00:00Z, so its readiness curve starts at 100.00 in READY."""
    set_clock("2026-08-01T00:00:00Z")
    scenario = seed_roster()
    scenario["incident"] = open_incident(
        scenario["headers"]["lead"],
        title="Credential stuffing attempts detected",
        scenario_code="DATA_BREACH",
    )
    material = file_material(
        scenario_code="DATA_BREACH",
        material_type="FAQ",
        title="Breach FAQ for the support desk",
    )
    material = review_material(
        material["id"],
        scenario["headers"]["comms"],
        reviewer_notes="Verified against the current incident-response runbook.",
    )
    assert_two_decimals(material["readiness_score"], 100.00, "readiness_score")
    assert_field(material, "readiness_state", "READY", "material")
    scenario["material"] = material
    return scenario


def test_sixteen_whole_days_of_decay_leaves_the_material_ready(api):
    """PRD §3.1: "the score is 100.00 less 2.50 for each of those whole days ...
    The material is `READY` while that score is at least 60.00 and `STALE` once it
    falls below. Concretely, sixteen whole days after review the score is 60.00
    and the material is still `READY`, because the threshold is inclusive."

    Design: Difficulty/boundary_precision_check/boundary_material_readiness_ready_at_exactly_sixty_on_sweep
    """
    scenario = _reviewed_faq_and_matching_incident()

    set_clock("2026-08-17T00:00:00Z")
    run_sla_sweep(scenario, incident_id=scenario["incident"]["id"])

    material = read_material(scenario["material"]["id"])
    assert_two_decimals(material["readiness_score"], 60.00, "readiness_score")
    assert_field(material, "readiness_state", "READY", "material")
    assert material["last_reviewed_at"].startswith("2026-08-01T00:00:00"), (
        "the review instant is the decay base and must not move, got "
        f"{material['last_reviewed_at']}"
    )


def test_the_seventeenth_day_of_decay_turns_the_material_stale(api):
    """PRD §3.1: "on the seventeenth day the score is 57.50 and the state becomes
    `STALE`", which the operator checkpoint applies because it "re-scores every
    prepared material whose `scenario_code` equals the incident's `scenario_code`,
    moving any `READY` asset whose decayed score has fallen below 60.00 into
    `STALE`" (PRD §3.3).

    Design: Difficulty/boundary_precision_check/boundary_material_readiness_ready_at_exactly_sixty_on_sweep
    """
    scenario = _reviewed_faq_and_matching_incident()

    set_clock("2026-08-17T00:00:00Z")
    run_sla_sweep(scenario, incident_id=scenario["incident"]["id"])
    set_clock("2026-08-18T00:00:00Z")
    run_sla_sweep(scenario, incident_id=scenario["incident"]["id"])

    material = read_material(scenario["material"]["id"])
    assert_two_decimals(material["readiness_score"], 57.50, "readiness_score")
    assert_field(material, "readiness_state", "STALE", "material")
    assert material["last_reviewed_at"].startswith("2026-08-01T00:00:00"), (
        "the review instant is the decay base and must not move, got "
        f"{material['last_reviewed_at']}"
    )


# ---------------------------------------------------------------------------
# The review deadline: a decision at exactly the deadline still counts
# ---------------------------------------------------------------------------


def _statement_in_review_with_a_nine_thirty_five_deadline():
    """A SEV2 incident whose statement was submitted at 09:05, so the SEV2 review
    window of thirty minutes puts ``review_deadline_at`` at 09:35 with both
    quorum tasks PENDING."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="EXEC_MISCONDUCT",
        title="Executive interview goes wrong",
        seat_roles=["INCIDENT_LEAD", "LEGAL_COUNSEL"],
    )
    set_clock("2026-08-10T09:05:00Z")
    draft_statement(
        scenario,
        statement_type="HOLDING",
        body="The remarks do not reflect company policy; a full statement follows.",
    )
    statement = submit_for_review(scenario)
    assert statement["review_deadline_at"].startswith("2026-08-10T09:35:00"), (
        "review_deadline_at must be submitted_at plus the SEV2 window, got "
        f"{statement['review_deadline_at']}"
    )
    assert_field(statement, "quorum_required", 2, "statement")
    tasks = scenario["tasks"]
    scenario["lead_task"] = next(
        task for task in tasks if task["required_team_role"] == "INCIDENT_LEAD"
    )
    scenario["counsel_task"] = next(
        task for task in tasks if task["required_team_role"] == "LEGAL_COUNSEL"
    )
    return scenario


def test_a_decision_at_exactly_the_review_deadline_still_counts(api):
    """PRD §3.5: "the current instant must not have passed `review_deadline_at`,
    so a decision made exactly at the deadline still counts and anything later
    yields `ERR_REVIEW_DEADLINE_PASSED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/boundary_review_deadline_equality_on_decide
    """
    scenario = _statement_in_review_with_a_nine_thirty_five_deadline()
    set_clock("2026-08-10T09:35:00Z")

    decided = validate_success(
        api.decide_approval_task(
            scenario["lead_task"]["id"],
            {"decision": "APPROVE"},
            scenario["headers"]["lead"],
        )
    )

    assert_state(decided, "APPROVED", "incident-lead task")
    assert decided["decided_at"].startswith("2026-08-10T09:35:00"), (
        f"decided_at must be the current instant, got {decided['decided_at']}"
    )
    statement = read_statement(scenario["statement"]["id"])
    assert_state(statement, "IN_REVIEW", "statement")
    assert_field(statement, "approvals_recorded", 1, "statement")
    assert_field(statement, "quorum_required", 2, "statement")


def test_a_decision_one_minute_past_the_review_deadline_is_refused(api):
    """PRD §3.5: "the current instant must not have passed `review_deadline_at` ...
    anything later yields `ERR_REVIEW_DEADLINE_PASSED` (HTTP 409)."

    The sibling counsel task is still PENDING and the statement is still
    IN_REVIEW with the one approval already recorded, so the round is neither
    completed nor collapsed by the refusal.

    Design: Difficulty/boundary_precision_check/boundary_review_deadline_equality_on_decide
    """
    scenario = _statement_in_review_with_a_nine_thirty_five_deadline()
    set_clock("2026-08-10T09:35:00Z")
    validate_success(
        api.decide_approval_task(
            scenario["lead_task"]["id"],
            {"decision": "APPROVE"},
            scenario["headers"]["lead"],
        )
    )

    set_clock("2026-08-10T09:36:00Z")
    before = read_task(scenario["counsel_task"]["id"])
    validate_error(
        api.decide_approval_task(
            scenario["counsel_task"]["id"],
            {"decision": "APPROVE"},
            scenario["headers"]["counsel"],
        ),
        ApiErrorId.ERR_REVIEW_DEADLINE_PASSED,
        409,
    )

    after = read_task(scenario["counsel_task"]["id"])
    assert_state(after, "PENDING", "counsel task")
    assert_no_write(before, after, "counsel task")
    statement = read_statement(scenario["statement"]["id"])
    assert_state(statement, "IN_REVIEW", "statement")
    assert_field(statement, "approvals_recorded", 1, "statement")
    assert_field(statement, "quorum_required", 2, "statement")
    assert_field(
        read_incident(scenario["incident"]["id"]), "open_approval_task_count", 1, "incident"
    )
