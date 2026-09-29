"""Endpoint behaviour: the logical clock, the operator checkpoint, signal
association, escalation-path verification, notice cancellation, filtered
pagination and the derived-counter read (PRD §2.3, §2.4, §2.5, §3.1-§3.6).
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    STARTUP_CLOCK,
    assert_field,
    assert_ids_equal,
    assert_ledger,
    assert_no_write,
    assert_pagination_meta,
    assert_posture,
    assert_severity,
    assert_state,
    assert_two_decimals,
    book_interview,
    cancel_notice_payload,
    clock_payload,
    confirm_interview,
    decide_task,
    draft_statement,
    file_material,
    find_by,
    issue_signal_payload,
    link_signal_payload,
    log_claim,
    make_program_admin_headers,
    make_social_listener_headers,
    queue_notice,
    read_incident,
    read_material,
    read_member,
    read_notice,
    read_signal,
    read_statement,
    read_task,
    record_signal,
    register_channel,
    register_member,
    review_material,
    seed_roster,
    set_clock,
    setup_activated_incident,
    setup_monitoring_incident,
    submit_for_review,
    tasks_for_statement,
    validate_error,
    validate_paginated,
    validate_success,
    verify_escalation_path_payload,
)


def test_clock_reposition_answers_current_utc_and_mutates_no_entity(api):
    """PRD §2.4: "Repositioning the clock is done by supplying a `to_iso8601`
    instant, and the call answers with the resulting `current_utc`.
    Repositioning the clock mutates no entity and triggers no sweep of any kind:
    time-driven state advances only when an operator explicitly asks for it,
    which is what makes the entire time-pressure model reproducible."

    Design: Corner/endpoints/corner_endpoint_clock_set_repositions_time_without_sweeping
    """
    roster = seed_roster()
    set_clock(STARTUP_CLOCK)
    material = file_material(
        scenario_code="DATA_BREACH", material_type="FAQ", title="Breach FAQ"
    )
    review_material(
        material["id"], roster["headers"]["comms"], reviewer_notes="Baseline review."
    )
    before = read_material(material["id"])
    assert before["last_reviewed_at"] is not None, "review did not stamp last_reviewed_at"

    moved = validate_success(
        api.set_clock(
            clock_payload("2026-08-21T00:00:00Z"), make_program_admin_headers()
        )
    )
    assert moved["current_utc"].startswith("2026-08-21T00:00:00"), (
        f"current_utc: expected the repositioned instant, got {moved['current_utc']}"
    )

    after = read_material(material["id"])
    assert_no_write(before, after, "prepared material")
    assert_field(
        after, "last_reviewed_at", before["last_reviewed_at"], "prepared material"
    )


def test_startup_clock_defaults_to_the_declared_epoch(api):
    """PRD §2.4: "The clock's startup value is exactly `2026-08-01T00:00:00Z`;
    until a `ProgramAdmin` repositions it, every reference to the current instant
    reads that default, and the server never falls back to real wall-clock time."

    Design: Corner/endpoints/corner_endpoint_startup_clock_defaults_to_the_declared_epoch
    """
    listener = register_member(full_name="Ray Lund", org_title="Social Analyst")
    listener_headers = make_social_listener_headers(listener["id"])
    channel = register_channel(name="National Wire", channel_type="MEDIA")

    signal = validate_success(
        api.create_issue_signal(
            issue_signal_payload(
                channel["id"],
                headline="First observation of the day",
                reach_score=55,
                sentiment_score=0.0,
                source_credibility_tier="A",
            ),
            listener_headers,
        ),
        201,
    )

    assert signal["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at: expected the startup instant, got {signal['created_at']}"
    )
    assert signal["detected_at"].startswith("2026-08-01T00:00:00"), (
        f"detected_at: expected the startup instant, got {signal['detected_at']}"
    )
    assert_state(signal, "OPEN", "signal")
    # 55 * 1.00 (tier A) + 8 (MEDIA channel bump) = 63.00 (PRD §3.2).
    assert_two_decimals(signal["escalation_score"], 63.00, "escalation_score")


def test_sla_sweep_expires_the_overdue_task_then_latches_the_breach(api):
    """PRD §3.3: "An operator checkpoint — available to the program
    administrator, the incident lead and the communications lead — advances every
    time-driven consequence at the current logical clock reading for one
    incident. It latches `sla_breached` when the current instant has reached
    `holding_statement_due_at` and no holding statement has been published. It
    expires approval tasks that have outrun their review deadline, pushing their
    statements into the revision loop and thereby blocking the notices those
    statements carry."

    Design: Corner/endpoints/corner_endpoint_sla_sweep_expires_task_then_latches_breach
    """
    scenario = setup_activated_incident(tier="SEV2", clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    # SEV2 activated at 09:00: holding due 10:00, review window 30 minutes.
    assert scenario["incident"]["holding_statement_due_at"].startswith(
        "2026-08-10T10:00:00"
    ), (
        "holding_statement_due_at: expected activated_at plus the SEV2 window, got "
        f"{scenario['incident']['holding_statement_due_at']}"
    )

    draft_statement(scenario, statement_type="HOLDING")
    notice = queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1000)
    submit_for_review(scenario)
    tasks = tasks_for_statement(scenario["statement"]["id"])
    assert len(tasks) == 2, f"SEV2 quorum is 2 seats, got {len(tasks)} tasks"
    before = read_incident(incident_id)

    set_clock("2026-08-10T09:45:00Z")
    first = validate_success(api.sla_sweep(incident_id, scenario["headers"]["lead"]))
    assert first["version"] == before["version"] + 1, (
        f"the checkpoint must increment version by exactly 1: "
        f"{before['version']} -> {first['version']}"
    )
    assert_field(first, "sla_breached", False, "incident")
    assert_posture(first, "RESTRICTED")
    assert_ledger(first, "blocked_notice_count", 1)
    assert_ledger(first, "open_approval_task_count", 0)

    expired = [read_task(task["id"]) for task in tasks]
    for task in expired:
        assert_state(task, "EXPIRED", "approval task")
        assert task["decided_at"] is not None, "expiry must stamp decided_at"
        assert task["decided_at"].startswith("2026-08-10T09:45"), (
            f"decided_at: expected the sweep instant, got {task['decided_at']}"
        )

    statement = read_statement(scenario["statement"]["id"])
    assert_state(statement, "REVISION_REQUESTED", "statement")
    assert_field(statement, "revision_round", 0, "statement")
    assert_state(read_notice(notice["id"]), "BLOCKED", "notice")

    set_clock("2026-08-10T10:00:00Z")
    second = validate_success(api.sla_sweep(incident_id, scenario["headers"]["lead"]))
    assert_field(second, "sla_breached", True, "incident")
    assert second["version"] == first["version"] + 1, (
        f"the second checkpoint must increment version by exactly 1: "
        f"{first['version']} -> {second['version']}"
    )
    assert_posture(second, "RESTRICTED")
    for task in expired:
        settled = read_task(task["id"])
        assert_state(settled, "EXPIRED", "approval task")
        assert_field(settled, "decided_at", task["decided_at"], "approval task")


def test_signal_link_rejects_an_unknown_incident_then_writes_both_sides(api):
    """PRD §2.5: "The same catalogue governs foreign keys carried in a request
    body: an `incident_id`, `channel_id`, `member_id`, `statement_id`,
    `spokesperson_member_id`, `supersedes_statement_id` or
    `correction_statement_id` that does not resolve produces the not-found error
    belonging to the referenced resource type, also at HTTP 404. Body-level
    foreign-key resolution applies to every creation endpoint and additionally to
    signal linking and to correction issuance."

    Design: Corner/endpoints/corner_endpoint_signal_link_requires_existing_incident_then_associates
    """
    scenario = setup_monitoring_incident(clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    listener_headers = scenario["headers"]["listener"]
    signal = record_signal(
        scenario["channel"]["id"],
        listener_headers,
        headline="Trade blog notices slow responses",
    )
    before = read_incident(incident_id)

    validate_error(
        api.link_issue_signal(
            signal["id"], link_signal_payload(NON_EXISTENT_UUID), listener_headers
        ),
        "ERR_INCIDENT_NOT_FOUND",
    )
    refused = read_signal(signal["id"])
    assert_state(refused, "OPEN", "signal")
    assert_field(refused, "incident_id", None, "signal")
    assert_no_write(before, read_incident(incident_id), "incident")

    linked = validate_success(
        api.link_issue_signal(
            signal["id"], link_signal_payload(incident_id), listener_headers
        )
    )
    assert_state(linked, "LINKED", "signal")
    assert_field(linked, "incident_id", incident_id, "signal")

    incident = read_incident(incident_id)
    assert_ledger(incident, "linked_signal_count", 1)
    assert_ledger(incident, "escalated_signal_count", 0)
    assert incident["version"] == before["version"] + 1, (
        "linking must increment the incident version by exactly 1: "
        f"{before['version']} -> {incident['version']}"
    )


def test_inline_incident_id_starts_the_signal_linked(api):
    """PRD §3.2: "Supplying `incident_id` at creation links the signal to that
    incident immediately, so it starts life in state `LINKED`; omitting it leaves
    the signal in `OPEN`, and it must be linked before it can ever be escalated."

    Design: Corner/endpoints/corner_endpoint_inline_incident_id_starts_the_signal_linked
    """
    scenario = setup_monitoring_incident(clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    channel_id = scenario["channel"]["id"]
    listener_headers = scenario["headers"]["listener"]

    inline = validate_success(
        api.create_issue_signal(
            issue_signal_payload(
                channel_id,
                headline="Signal recorded with an incident already known",
                reach_score=55,
                sentiment_score=0.0,
                source_credibility_tier="A",
                incident_id=incident_id,
            ),
            listener_headers,
        ),
        201,
    )
    loose = validate_success(
        api.create_issue_signal(
            issue_signal_payload(
                channel_id,
                headline="Signal recorded before triage",
                reach_score=55,
                sentiment_score=0.0,
                source_credibility_tier="A",
            ),
            listener_headers,
        ),
        201,
    )

    assert_state(inline, "LINKED", "inline signal")
    assert_field(inline, "incident_id", incident_id, "inline signal")
    assert_state(loose, "OPEN", "loose signal")
    assert_field(loose, "incident_id", None, "loose signal")
    # Identical inputs freeze an identical score: 55 * 1.00 + 8 = 63.00 (PRD §3.2).
    assert_two_decimals(inline["escalation_score"], 63.00, "inline escalation_score")
    assert_two_decimals(loose["escalation_score"], 63.00, "loose escalation_score")

    incident = read_incident(incident_id)
    assert_ledger(incident, "linked_signal_count", 1)
    assert_ledger(incident, "escalated_signal_count", 0)


def test_verify_escalation_path_records_the_contact_and_bumps_the_version(api):
    """PRD §3.1: "Verifying the escalation path supplies a
    `verified_contact_reference`, which the server records verbatim, moves
    `escalation_path_state` from `UNVERIFIED` to `VERIFIED`, and increments the
    channel's `version` by 1."

    Design: Corner/endpoints/corner_endpoint_verify_escalation_path_records_contact_reference
    """
    set_clock("2026-08-10T09:00:00Z")
    channel = register_channel(
        name="ShortVideo App",
        channel_type="SOCIAL",
        platform_escalation_contact="trust@shortvideo.example",
    )
    assert_field(channel, "escalation_path_state", "UNVERIFIED", "channel")
    assert_field(channel, "verified_contact_reference", None, "channel")

    verified = validate_success(
        api.verify_escalation_path(
            channel["id"],
            verify_escalation_path_payload(verified_contact_reference="TS-CASE-7781"),
            make_program_admin_headers(),
        )
    )
    assert_field(verified, "escalation_path_state", "VERIFIED", "channel")
    assert_field(verified, "verified_contact_reference", "TS-CASE-7781", "channel")
    assert_field(
        verified,
        "platform_escalation_contact",
        "trust@shortvideo.example",
        "channel",
    )
    assert verified["version"] == channel["version"] + 1, (
        "verification must increment the channel version by exactly 1: "
        f"{channel['version']} -> {verified['version']}"
    )
    assert_ledger(verified, "reserved_correction_minutes", 0)


def test_cancelling_the_last_blocked_notice_reopens_the_posture(api):
    """PRD §3.6: "Cancelling the last blocked notice is a common way out of a
    `RESTRICTED` posture: when `blocked_notice_count` falls to 0 and
    `sla_breached` is false, the posture returns to `OPEN`."

    Design: Corner/endpoints/corner_endpoint_notice_cancel_from_blocked_reopens_the_posture
    """
    scenario = setup_activated_incident(tier="SEV2", clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    draft_statement(
        scenario,
        statement_type="HOLDING",
        body="We respect the ballot outcome and will meet representatives.",
    )
    notice = queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1000)
    submit_for_review(scenario)

    lead_task = find_by(scenario["tasks"], required_team_role="INCIDENT_LEAD")
    decide_task(lead_task, "REJECT", "Legal wants to see this first.")
    assert_state(read_notice(notice["id"]), "BLOCKED", "notice")
    restricted = read_incident(incident_id)
    assert_posture(restricted, "RESTRICTED")
    assert_ledger(restricted, "blocked_notice_count", 1)

    cancelled = validate_success(
        api.cancel_stakeholder_notice(
            notice["id"],
            cancel_notice_payload(
                cancel_reason="Message will be reissued after legal review."
            ),
            scenario["headers"]["comms"],
        )
    )
    assert_state(cancelled, "CANCELLED", "notice")
    assert_field(
        cancelled,
        "cancel_reason",
        "Message will be reissued after legal review.",
        "notice",
    )
    assert_field(cancelled, "released_at", None, "notice")
    assert_two_decimals(cancelled["reach_contribution"], 0.00, "reach_contribution")

    incident = read_incident(incident_id)
    assert_ledger(incident, "blocked_notice_count", 0)
    assert_field(incident, "sla_breached", False, "incident")
    assert_posture(incident, "OPEN")
    assert_state(
        read_statement(scenario["statement"]["id"]), "REVISION_REQUESTED", "statement"
    )


def test_filtered_pagination_window_is_stable(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and
    `offset` echoing the effective values used, `total_count` giving the number of
    records matching the filters before the page window is applied, and
    `has_more` indicating whether any matching record remains beyond the current
    window."

    Design: Corner/endpoints/corner_endpoint_filtered_pagination_window_is_stable
    """
    roster = seed_roster()
    listener_headers = roster["headers"]["listener"]
    channel_a = register_channel(name="Channel A", channel_type="MEDIA")
    channel_b = register_channel(name="Channel B", channel_type="SOCIAL")

    # Each signal is recorded at a later logical instant so the declared default
    # ordering by created_at ascending is unambiguous (PRD §2.3, §2.4).
    channel_a_ids = []
    for index, reach in enumerate([10, 20, 30, 40, 50]):
        set_clock(f"2026-08-10T09:0{index}:00Z")
        recorded = record_signal(
            channel_a["id"],
            listener_headers,
            headline=f"S{index + 1}",
            reach_score=reach,
            source_credibility_tier="C",
        )
        channel_a_ids.append(recorded["id"])
    for index, reach in enumerate([60, 70]):
        set_clock(f"2026-08-10T09:0{5 + index}:00Z")
        record_signal(
            channel_b["id"],
            listener_headers,
            headline=f"B{index + 1}",
            reach_score=reach,
            source_credibility_tier="C",
        )

    rows, meta = validate_paginated(
        api.list_issue_signals(
            listener_headers,
            {"channel_id": channel_a["id"], "limit": 2, "offset": 2},
        )
    )
    assert_ids_equal(rows, channel_a_ids[2:4])
    assert_pagination_meta(meta, total_count=5, has_more=True)
    assert meta["limit"] == 2, f"meta.limit: expected 2, got {meta['limit']}"
    assert meta["offset"] == 2, f"meta.offset: expected 2, got {meta['offset']}"
    for row in rows:
        assert_field(row, "channel_id", channel_a["id"], "signal")

    unfiltered, all_meta = validate_paginated(api.list_issue_signals(listener_headers))
    assert_pagination_meta(all_meta, total_count=7, has_more=False)
    assert all_meta["limit"] == 10, (
        f"omitted limit defaults to 10, got {all_meta['limit']}"
    )
    assert all_meta["offset"] == 0, (
        f"omitted offset defaults to 0, got {all_meta['offset']}"
    )
    assert len(unfiltered) == 7, (
        f"expected all 7 signals inside the default window, got {len(unfiltered)}"
    )


def test_incident_read_reports_every_derived_counter(api):
    """PRD §3.2: "On success the signal's `incident_id` is written, the
    incident's `linked_signal_count` — the number of that incident's signals in
    state `LINKED` or `ESCALATED` — is recomputed, and the incident's `version` is
    incremented by 1."

    Design: Corner/endpoints/corner_endpoint_computed_read_reports_every_derived_counter
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="PLANT_INCIDENT"
    )
    incident_id = scenario["incident"]["id"]

    cold = validate_success(
        api.create_issue_signal(
            issue_signal_payload(
                scenario["channel"]["id"],
                headline="Low-credibility follow-up",
                reach_score=40,
                sentiment_score=0.0,
                source_credibility_tier="C",
                incident_id=incident_id,
            ),
            scenario["headers"]["listener"],
        ),
        201,
    )
    # 40 * 0.60 (tier C) + 8 (MEDIA) = 32.00, below the 70.00 gate (PRD §3.2).
    assert_two_decimals(cold["escalation_score"], 32.00, "escalation_score")

    log_claim(scenario, virality_score=30.00, claim_text="Toxic gas was released.")
    book_interview(
        scenario,
        "2026-08-12T10:00:00Z",
        "2026-08-12T10:45:00Z",
        anticipated_question_count=8,
        outlet_name="Morning Wire",
    )
    confirm_interview(scenario, high_risk_answers_approved_count=3)

    incident = validate_success(
        api.get_incident(incident_id, scenario["headers"]["exec"])
    )
    assert_ledger(incident, "linked_signal_count", 2)
    assert_ledger(incident, "escalated_signal_count", 1)
    # The merely LINKED 32.00 signal does not hold the provisional peak.
    assert_severity(incident, "SEV2", 83.00, "PROVISIONAL")
    assert_ledger(incident, "open_claim_count", 1)
    assert_ledger(incident, "confirmed_interview_count", 1)
    assert_ledger(incident, "open_approval_task_count", 0)
    assert_ledger(incident, "released_notice_count", 0)
    assert_ledger(incident, "blocked_notice_count", 0)

    assert_state(read_signal(cold["id"]), "LINKED", "signal")
    assert_ledger(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 45
    )
