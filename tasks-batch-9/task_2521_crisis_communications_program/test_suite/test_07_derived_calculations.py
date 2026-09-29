"""Derived calculations: pinned formulas, pinned constants and pinned rounding.

Every expected number below is re-derived from the formula the PRD states, in the
evaluation order the PRD pins.
"""

from test_helpers import (
    assert_containment,
    assert_field,
    assert_four_decimals,
    assert_ledger,
    assert_no_write,
    assert_severity,
    assert_state,
    assert_timestamp_format,
    assert_two_decimals,
    close_claim,
    draft_statement,
    escalate_claim_to_platform,
    file_material,
    issue_signal_payload,
    log_claim,
    queue_notice,
    read_channel,
    read_claim,
    read_incident,
    read_material,
    read_notice,
    read_signal,
    read_statement,
    register_channel,
    release_notice,
    resolve_incident,
    review_material,
    run_sla_sweep,
    score_review,
    seed_roster,
    set_clock,
    setup_activated_incident,
    setup_monitoring_incident,
    setup_open_review,
    setup_published_statement,
    setup_statement_in_review,
    triage_claim,
    validate_error,
    validate_paginated,
    validate_success,
    verify_channel_path,
)


def _assert_instant(value, expected_prefix, label="instant"):
    """Every instant is an ISO 8601 UTC timestamp rendered with three fractional
    digits, so a stamped instant is compared on its second-precision prefix
    (PRD §2.4)."""
    assert_timestamp_format(value)
    assert value.startswith(expected_prefix), (
        f"{label}: expected {expected_prefix}, got {value}"
    )


# ---------------------------------------------------------------------------
# Issue signal escalation score (PRD §3.2)
# ---------------------------------------------------------------------------


def test_sentiment_penalty_rounds_half_up_to_two_decimals(api):
    """PRD §3.2: "the sentiment penalty takes the negation of `sentiment_score`,
    keeps it only if it is greater than 0.0 and treats it as 0.0 otherwise,
    multiplies the result by a scale of 30, and rounds half up to two decimals"
    ... "the base component and the sentiment penalty are each rounded to two
    decimals **before** anything is summed".

    Design: Corner/calculations/corner_signal_score_sentiment_penalty_rounds_half_up
    """
    set_clock("2026-08-10T09:00:00Z")
    roster = seed_roster()
    channel = register_channel(name="ShortVideo App", channel_type="SOCIAL")

    response = api.create_issue_signal(
        issue_signal_payload(
            channel["id"],
            headline="Clip of a queue outside the depot",
            reach_score=55,
            sentiment_score=-0.1025,
            source_credibility_tier="C",
        ),
        roster["headers"]["listener"],
    )
    signal = validate_success(response, 201)

    # base 55 * 0.60 = 33.00; sentiment penalty round_half_up(0.1025 * 30) =
    # round_half_up(3.075) = 3.08; SOCIAL bump 4; no regulatory bump.
    # 33.00 + 3.08 + 4 = 40.08 (not 40.07, which is what a truncating or
    # banker's-rounding penalty would yield).
    assert_two_decimals(signal["escalation_score"], 40.08, "escalation_score")
    assert_state(signal, "OPEN", "signal")
    _assert_instant(signal["detected_at"], "2026-08-10T09:00:00", "detected_at")

    stored = read_signal(signal["id"])
    assert_two_decimals(stored["escalation_score"], 40.08, "escalation_score")


def test_regulatory_bumps_stack_while_positive_sentiment_adds_nothing(api):
    """PRD §3.2: "a channel bump is added according to the surface: 8 points for
    a `MEDIA` channel, 4 for a `SOCIAL` channel, and 15 for a `REGULATORY`
    channel. Fourth, a flat regulatory bump of 12 points is added when
    `regulatory_flag` is true, and nothing when it is false." ... "positive
    sentiment therefore contributes exactly nothing and never reduces the
    score."

    Design: Corner/calculations/corner_signal_score_regulatory_constants_and_one_sided_sentiment
    """
    set_clock("2026-08-10T09:00:00Z")
    roster = seed_roster()
    channel = register_channel(
        name="Safety Regulator Docket", channel_type="REGULATORY"
    )

    response = api.create_issue_signal(
        issue_signal_payload(
            channel["id"],
            headline="Docket entry opens an inspection",
            reach_score=60,
            sentiment_score=0.8,
            source_credibility_tier="A",
            regulatory_flag=True,
        ),
        roster["headers"]["listener"],
    )
    signal = validate_success(response, 201)

    # base 60 * 1.00 = 60.00; negation of +0.8 is not greater than 0.0 so the
    # penalty is 0.00; REGULATORY bump 15; regulatory_flag bump 12.
    # 60.00 + 0.00 + 15 + 12 = 87.00
    assert_two_decimals(signal["escalation_score"], 87.00, "escalation_score")
    assert_field(signal, "regulatory_flag", True, "signal")
    assert_state(signal, "OPEN", "signal")


# ---------------------------------------------------------------------------
# Service-level and review windows keyed on the severity tier (PRD §3.3, §3.5)
# ---------------------------------------------------------------------------


def test_sev2_selects_the_sev2_row_of_both_minute_tables(api):
    """PRD §3.3: "`holding_statement_due_at` is `activated_at` plus the
    service-level window belonging to the current `severity_tier`: half an hour
    for `SEV1`, one hour for `SEV2`, three hours for `SEV3`, and eight hours for
    `SEV4`." PRD §3.5: "`review_deadline_at` is set to `submitted_at` plus the
    review window belonging to the incident's current `severity_tier`: fifteen
    minutes for `SEV1`, half an hour for `SEV2`, an hour and a half for `SEV3`,
    and four hours for `SEV4`."

    Design: Corner/calculations/corner_sla_constants_selected_per_severity_tier_sev2
    """
    scenario = setup_statement_in_review(clock="2026-08-10T09:00:00Z", tier="SEV2")
    incident = read_incident(scenario["incident"]["id"])
    statement = read_statement(scenario["statement"]["id"])

    # One MEDIA signal, reach 75, credibility A: 75 * 1.00 + 8 = 83.00, which
    # bands SEV2 because it is at least 70.00 and below 90.00.
    assert_severity(incident, "SEV2", 83.00, "PROVISIONAL")

    # activated_at 09:00:00 + the SEV2 holding window of 60 minutes.
    _assert_instant(
        incident["holding_statement_due_at"],
        "2026-08-10T10:00:00",
        "holding_statement_due_at",
    )
    _assert_instant(statement["submitted_at"], "2026-08-10T09:00:00", "submitted_at")
    # submitted_at 09:00:00 + the SEV2 review window of 30 minutes.
    _assert_instant(
        statement["review_deadline_at"],
        "2026-08-10T09:30:00",
        "review_deadline_at",
    )

    assert_state(statement, "IN_REVIEW", "statement")
    assert_field(statement, "quorum_required", 2, "statement")
    assert_ledger(incident, "open_approval_task_count", 2)
    assert_field(incident, "sla_breached", False, "incident")


def test_sev1_quorum_fans_out_three_tasks_in_the_declared_seat_order(api):
    """PRD §3.5: "The list of required approver seats always begins with
    `INCIDENT_LEAD`. `LEGAL_COUNSEL` is appended when the incident's
    `severity_tier` is `SEV1` or `SEV2`, or when the statement's
    `privilege_marked` flag is true ... `EXEC_SPONSOR` is appended when and only
    when the tier is `SEV1`. `quorum_required` is the number of seats in that
    list ... approval tasks are created in exactly that order" and
    "`is_veto_seat` is true for the counsel task and false for the others".

    Design: Corner/calculations/corner_quorum_requirement_sev1_three_roles_in_declared_order
    """
    scenario = setup_statement_in_review(clock="2026-08-10T09:00:00Z", tier="SEV1")
    incident = read_incident(scenario["incident"]["id"])
    statement = read_statement(scenario["statement"]["id"])

    # One MEDIA signal, reach 88, credibility A: 88 * 1.00 + 8 = 96.00, at least
    # 90.00 and therefore SEV1.
    assert_severity(incident, "SEV1", 96.00, "PROVISIONAL")
    # activated_at 09:00:00 + the SEV1 holding window of 30 minutes.
    _assert_instant(
        incident["holding_statement_due_at"],
        "2026-08-10T09:30:00",
        "holding_statement_due_at",
    )
    # submitted_at 09:00:00 + the SEV1 review window of 15 minutes.
    _assert_instant(
        statement["review_deadline_at"],
        "2026-08-10T09:15:00",
        "review_deadline_at",
    )
    assert_field(statement, "quorum_required", 3, "statement")

    rows, meta = validate_paginated(
        api.list_approval_tasks(
            scenario["headers"]["admin"], {"statement_id": statement["id"]}
        )
    )
    assert meta["total_count"] == 3, f"expected 3 approval tasks, got {meta['total_count']}"
    assert [row["required_team_role"] for row in rows] == [
        "INCIDENT_LEAD",
        "LEGAL_COUNSEL",
        "EXEC_SPONSOR",
    ], "approval tasks are not in the pinned seat order"
    assert [row["assignee_member_id"] for row in rows] == [
        scenario["ids"]["lead"],
        scenario["ids"]["counsel"],
        scenario["ids"]["exec"],
    ], "approval tasks were not routed to the acknowledged holders of each seat"
    assert [row["is_veto_seat"] for row in rows] == [False, True, False], (
        "is_veto_seat must be true for the counsel task only"
    )
    for row in rows:
        assert_state(row, "PENDING", "approval task")
        assert_field(row, "revision_round", 0, "approval task")

    assert_ledger(incident, "open_approval_task_count", 3)


# ---------------------------------------------------------------------------
# Stakeholder reach index input set (PRD §3.6)
# ---------------------------------------------------------------------------


def test_reach_index_counts_released_notices_only(api):
    """PRD §3.6: "The incident's `stakeholder_reach_index` is then rebuilt from
    scratch on every release: taking only the notices on that incident in state
    `RELEASED` — `QUEUED`, `BLOCKED` and `CANCELLED` notices are excluded
    entirely" and "Notices that are not `RELEASED` carry a `reach_contribution`
    of 0.00."

    Design: Corner/calculations/corner_reach_index_input_set_counts_released_notices_only
    """
    scenario = setup_published_statement(clock="2026-08-10T09:00:00Z", tier="SEV2")
    employee = queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1000)
    customer = queue_notice(scenario, audience="CUSTOMER", estimated_reach=4000)

    released = release_notice(scenario, employee["id"])

    # EMPLOYEE weight 1.00 * 1000 / 1000 = 1.00
    assert_state(released, "RELEASED", "employee notice")
    assert_two_decimals(released["reach_contribution"], 1.00, "reach_contribution")

    # The CUSTOMER notice would have contributed 1.25 * 4000 / 1000 = 5.00 had a
    # non-RELEASED row been allowed into the input set.
    untouched = read_notice(customer["id"])
    assert_state(untouched, "QUEUED", "customer notice")
    assert_two_decimals(untouched["reach_contribution"], 0.00, "reach_contribution")

    incident = read_incident(scenario["incident"]["id"])
    assert_two_decimals(
        incident["stakeholder_reach_index"], 1.00, "stakeholder_reach_index"
    )
    assert_ledger(incident, "released_notice_count", 1)
    _assert_instant(
        incident["holding_statement_published_at"],
        "2026-08-10T09:00:00",
        "holding_statement_published_at",
    )


# ---------------------------------------------------------------------------
# Containment priority family (PRD §3.3, §3.8)
# ---------------------------------------------------------------------------


def test_containment_exposure_drops_when_the_claim_leaves_the_input_set(api):
    """PRD §3.3: "The exposure component is the sum of `virality_score` across
    every misinformation claim on the incident in state `DETECTED`, `TRIAGED`,
    `PLATFORM_ESCALATED` or `CORRECTION_ISSUED` ... `base_containment_score` is
    seven tenths of the tier's point value plus three tenths of that exposure
    component". PRD §3.8: closing a claim "recompute[s] the containment family
    because the closed claim no longer contributes exposure".

    Design: Corner/calculations/corner_containment_exposure_drops_when_claim_leaves_the_input_set
    """
    scenario = setup_activated_incident(clock="2026-08-10T09:00:00Z", tier="SEV2")
    verify_channel_path(scenario["channel"]["id"])

    # At activation there are no claims, so exposure is 0.00:
    # base = 0.7 * 75 + 0.3 * 0.00 = 52.50, which sits below 55.00 and therefore
    # in LOW at rate 0.05; fee = round(52.50 * 0.05) = round(2.625) = 2.63;
    # total = 52.50 + 2.63 = 55.13.
    at_activation = read_incident(scenario["incident"]["id"])
    assert_containment(at_activation, 52.50, 0.05, 55.13)

    log_claim(scenario, virality_score=60.00)
    triage_claim(scenario)

    # Exposure is now 60.00: base = 0.7 * 75 + 0.3 * 60.00 = 52.50 + 18.00 =
    # 70.50, which is at least 55.00 and therefore MEDIUM at rate 0.10;
    # fee = 7.05; total = 77.55.
    after_triage = read_incident(scenario["incident"]["id"])
    assert_containment(after_triage, 70.50, 0.10, 77.55)

    escalate_claim_to_platform(scenario)
    close_claim(scenario, actor="listener")

    # The CLOSED claim is outside the exposure input set, so the family is
    # recomputed from scratch back to its pre-claim values rather than latching
    # the 77.55 peak.
    after_close = read_incident(scenario["incident"]["id"])
    assert_containment(after_close, 52.50, 0.05, 55.13)
    assert_ledger(after_close, "open_claim_count", 0)

    claim = read_claim(scenario["claim"]["id"])
    assert_state(claim, "CLOSED", "claim")
    assert_field(claim, "resolution_branch", "PLATFORM", "claim")
    assert_field(claim, "takedown_confirmed", True, "claim")
    assert_field(claim, "corrected", False, "claim")

    channel = read_channel(scenario["channel"]["id"])
    assert_ledger(channel, "open_escalation_count", 0)


# ---------------------------------------------------------------------------
# Prepared-material readiness decay (PRD §3.1)
# ---------------------------------------------------------------------------


def test_material_readiness_decay_floors_at_zero(api):
    """PRD §3.1: "the number of elapsed days is the whole number of complete
    24-hour periods between `last_reviewed_at` and the current instant,
    discarding any partial day, and the score is 100.00 less 2.50 for each of
    those whole days, rounded half up to two decimals and never allowed below
    0.00. The material is `READY` while that score is at least 60.00 and `STALE`
    once it falls below."

    Design: Corner/calculations/corner_material_readiness_decay_floors_at_zero
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-01T00:00:00Z", scenario_code="DATA_BREACH"
    )
    material = file_material(
        scenario_code="DATA_BREACH",
        material_type="DARK_SITE_PAGE",
        title="Breach dark site landing page",
        dark_site_url="https://dark.example/breach",
    )
    reviewed = review_material(
        material["id"],
        scenario["headers"]["comms"],
        reviewer_notes="Baseline review at the epoch clock.",
    )
    assert_two_decimals(reviewed["readiness_score"], 100.00, "readiness_score")
    assert_field(reviewed, "readiness_state", "READY", "material")

    # 2026-08-01T00:00:00Z to 2026-09-15T00:00:00Z is 31 + 14 = 45 whole days.
    set_clock("2026-09-15T00:00:00Z")
    swept = run_sla_sweep(scenario)
    assert swept["response_state"] == "MONITORING", (
        "the checkpoint must not move the response dimension"
    )

    decayed = read_material(material["id"])
    # 100.00 - 2.50 * 45 = -12.50, which the floor clamps to exactly 0.00.
    assert_two_decimals(decayed["readiness_score"], 0.00, "readiness_score")
    assert_field(decayed, "readiness_state", "STALE", "material")
    _assert_instant(
        decayed["last_reviewed_at"], "2026-08-01T00:00:00", "last_reviewed_at"
    )


# ---------------------------------------------------------------------------
# Reputation delta variants (PRD §3.9)
# ---------------------------------------------------------------------------


def test_raw_scoring_method_reports_the_undamped_delta(api):
    """PRD §3.9: "Both delta variants are **always** computed and both are
    always stored, whichever method is chosen ... The adjusted delta is the raw
    delta multiplied by one less the `exposure_factor`, plus the efficacy bonus,
    rounded half up to two decimals ... `reported_delta` is then the raw variant
    when `scoring_method` is `RAW` and the adjusted variant when it is
    `ADJUSTED`."

    Design: Corner/calculations/corner_reputation_delta_raw_method_reports_the_undamped_value
    """
    scenario = setup_activated_incident(
        clock="2026-08-10T09:00:00Z", tier="SEV2", reputation_index_before=60.00
    )
    setup_published_statement(scenario)
    notice = queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1010)
    release_notice(scenario, notice["id"])

    resolve_incident(scenario, reputation_index_after=52.70)
    review = scenario["review"]

    # reach index = 1.00 * 1010 / 1000 = 1.01, so exposure_factor = 1.01 / 100 =
    # 0.0101, below the 0.50 cap.
    assert_four_decimals(review["exposure_factor"], 0.0101, "exposure_factor")
    assert_field(review, "total_claim_count", 0, "review")
    assert_field(review, "corrected_claim_count", 0, "review")

    scored = score_review(scenario, scoring_method="RAW", playbook_update_count=2)

    # raw = 52.70 - 60.00 = -7.30
    assert_two_decimals(scored["reputation_delta_raw"], -7.30, "reputation_delta_raw")
    # correction ratio 0.0000 with no claims, so the efficacy bonus is
    # 2.50 * 0.0000 = 0.00; adjusted = -7.30 * (1 - 0.0101) + 0.00 = -7.22627,
    # which rounds half up to -7.23.
    assert_two_decimals(
        scored["reputation_delta_adjusted"], -7.23, "reputation_delta_adjusted"
    )
    # RAW selects the undamped variant even though the adjusted column is stored.
    assert_two_decimals(scored["reported_delta"], -7.30, "reported_delta")
    assert_state(scored, "SCORED", "review")
    assert_field(scored, "playbook_update_count", 2, "review")
    _assert_instant(scored["scored_at"], "2026-08-10T09:00:00", "scored_at")

    incident = read_incident(scenario["incident"]["id"])
    assert_two_decimals(
        incident["reputation_delta_reported"], -7.30, "reputation_delta_reported"
    )


def test_zero_claim_guard_keeps_the_correction_ratio_at_four_zero_decimals(api):
    """PRD §3.9: "The correction ratio is exactly 0.0000 when
    `total_claim_count` is 0, and otherwise `corrected_claim_count` divided by
    `total_claim_count`, rounded to four decimals. The efficacy bonus is a
    maximum of 2.50 multiplied by that correction ratio, rounded half up to two
    decimals."

    Design: Corner/calculations/corner_reputation_delta_zero_claim_guard_avoids_division
    """
    scenario = setup_open_review(
        clock="2026-08-10T09:00:00Z",
        tier="SEV2",
        reputation_index_after=52.70,
        reputation_index_before=60.00,
    )
    review = scenario["review"]

    # No notice was ever released, so stakeholder_reach_index is 0.00 and
    # exposure_factor = 0.00 / 100 = 0.0000.
    assert_four_decimals(review["exposure_factor"], 0.0000, "exposure_factor")
    assert_field(review, "total_claim_count", 0, "review")

    scored = score_review(scenario, scoring_method="ADJUSTED", playbook_update_count=0)

    # raw = 52.70 - 60.00 = -7.30; the guarded ratio is 0.0000 so the bonus is
    # 0.00 and adjusted = -7.30 * (1 - 0.0000) + 0.00 = -7.30.
    assert_two_decimals(scored["reputation_delta_raw"], -7.30, "reputation_delta_raw")
    assert_two_decimals(
        scored["reputation_delta_adjusted"], -7.30, "reputation_delta_adjusted"
    )
    assert_two_decimals(scored["reported_delta"], -7.30, "reported_delta")

    incident = read_incident(scenario["incident"]["id"])
    # The escalated set holds one signal scoring 83.00, so peak and average are
    # both 83.00 and final = 0.6 * 83.00 + 0.4 * 83.00 = 83.00, banding SEV2.
    assert_field(incident, "final_severity_tier", "SEV2", "incident")
    assert_two_decimals(
        incident["final_severity_score"], 83.00, "final_severity_score"
    )
    assert_field(incident, "severity_basis", "FINAL", "incident")


# ---------------------------------------------------------------------------
# Approval-task routing (PRD §3.5)
# ---------------------------------------------------------------------------


def test_empty_approver_pool_creates_no_tasks_at_all(api):
    """PRD §3.5: "If the pool for **any** required seat is empty, the entire
    submission fails with `ERR_APPROVER_UNAVAILABLE` (HTTP 409) and no approval
    task is created for any seat at all; the operation is atomic."

    Design: Corner/calculations/corner_approval_routing_empty_pool_creates_no_tasks
    """
    scenario = setup_activated_incident(
        clock="2026-08-10T09:00:00Z",
        tier="SEV2",
        scenario_code="REGULATORY_PROBE",
        seat_roles=["INCIDENT_LEAD"],
    )
    draft = draft_statement(scenario)
    assert_state(draft, "DRAFT", "statement")

    # A SEV2 tier appends LEGAL_COUNSEL to the required seat list, and no
    # LEGAL_COUNSEL seat is ACKNOWLEDGED on this incident.
    response = api.submit_statement_review(draft["id"], scenario["headers"]["comms"])
    validate_error(response, "ERR_APPROVER_UNAVAILABLE")

    rows, meta = validate_paginated(
        api.list_approval_tasks(
            scenario["headers"]["admin"], {"statement_id": draft["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"routing is atomic, so no task may exist; got {meta['total_count']}"
    )
    assert rows == [], f"expected no approval tasks, got {rows}"

    after = read_statement(draft["id"])
    assert_state(after, "DRAFT", "statement")
    assert_field(after, "quorum_required", 0, "statement")
    assert_field(after, "submitted_at", None, "statement")
    assert_no_write(draft, after, "statement")

    incident = read_incident(scenario["incident"]["id"])
    assert_ledger(incident, "open_approval_task_count", 0)
