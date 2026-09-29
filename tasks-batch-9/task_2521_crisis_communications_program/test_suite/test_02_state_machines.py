"""State-machine behaviour: declared initial states, non-idempotent transitions,
precondition refusals, the full activation side-effect list, terminal-state
lockdown, the bounded revision cycle, the notice block/requeue cycle and the
prepared-material decay cycle (PRD §3.1, §3.2, §3.3, §3.5, §3.6, §3.9).
"""

from test_helpers import (
    approve_to_quorum,
    assert_containment,
    assert_field,
    assert_fields,
    assert_ledger,
    assert_no_write,
    assert_posture,
    assert_severity,
    assert_state,
    assert_two_decimals,
    assert_unchanged,
    decide_task,
    draft_statement,
    file_material,
    get_success_data,
    incident_payload,
    incident_version,
    issue_signal_payload,
    link_signal,
    escalate_signal,
    material_review_payload,
    monitored_channel_payload,
    prepared_material_payload,
    queue_notice,
    read_assignment,
    read_incident,
    read_material,
    read_member,
    read_notice,
    read_signal,
    read_statement,
    record_signal,
    resolve_incident_payload,
    revise_statement_payload,
    review_material,
    run_sla_sweep,
    seat_member,
    seed_roster,
    set_clock,
    setup_activated_incident,
    setup_monitoring_incident,
    setup_statement_in_review,
    submit_for_review,
    tasks_for_statement,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_statement_payload,
)


def test_freshly_created_rows_sit_in_their_declared_initial_states(api):
    """PRD §3.3: "A new incident begins in `response_state` `MONITORING`,
    `privilege_state` `NON_PRIVILEGED`, `comms_posture` `OPEN`, with
    `legal_hold_active` false, `sla_breached` false, a null `privilege_basis`."

    Design: Corner/state_machines/corner_initial_states_across_all_machines
    """
    set_clock("2026-08-10T09:00:00Z")
    scenario = seed_roster()

    channel = validate_success(
        api.create_monitored_channel(
            monitored_channel_payload(name="National Wire", channel_type="MEDIA"),
            scenario["headers"]["admin"],
        ),
        201,
    )
    incident = validate_success(
        api.create_incident(
            incident_payload(
                title="Cooling tower plume", scenario_code="PLANT_INCIDENT"
            ),
            scenario["headers"]["lead"],
        ),
        201,
    )
    signal = validate_success(
        api.create_issue_signal(
            issue_signal_payload(
                channel["id"], headline="Neighbour posts a photo", reach_score=55
            ),
            scenario["headers"]["listener"],
        ),
        201,
    )
    material = validate_success(
        api.create_prepared_material(
            prepared_material_payload(
                scenario_code="PLANT_INCIDENT",
                material_type="HOLDING_TEMPLATE",
                title="Plant incident holding template",
            ),
            scenario["headers"]["comms"],
        ),
        201,
    )

    assert_fields(
        incident,
        {
            "response_state": "MONITORING",
            "privilege_state": "NON_PRIVILEGED",
            "comms_posture": "OPEN",
            "legal_hold_active": False,
            "sla_breached": False,
            "privilege_basis": None,
        },
        "Incident",
    )
    assert_state(signal, "OPEN", "IssueSignal")
    assert_field(signal, "incident_id", None, "IssueSignal")
    assert_field(channel, "escalation_path_state", "UNVERIFIED", "MonitoredChannel")
    assert_field(material, "readiness_state", "DRAFT", "PreparedMaterial")
    assert signal.get("detected_at", "").startswith("2026-08-10T09:00:00"), (
        "detected_at must be stamped with the current logical instant, got "
        f"{signal.get('detected_at')!r}"
    )


def test_second_acknowledge_of_the_same_seat_is_refused(api):
    """PRD §3.3: "Only the seated person may accept the seat: acknowledgement
    advances `ASSIGNED → ACKNOWLEDGED`, stamps `acknowledged_at`, and recomputes
    the member's `active_assignment_count`; ... a seat that is not in `ASSIGNED`
    yields `ERR_ASSIGNMENT_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/corner_team_assignment_second_acknowledge_rejected
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-10T09:00:00Z", title="Payment processor outage"
    )
    lead_id = scenario["ids"]["lead"]
    lead_headers = scenario["headers"]["lead"]
    seat = seat_member(
        scenario["incident"]["id"],
        lead_id,
        "INCIDENT_LEAD",
        lead_headers,
        acknowledge=False,
    )
    assert_state(seat, "ASSIGNED", "TeamAssignment")

    acknowledged = validate_success(
        api.acknowledge_team_assignment(seat["id"], lead_headers)
    )
    assert_state(acknowledged, "ACKNOWLEDGED", "TeamAssignment")
    assert acknowledged.get("acknowledged_at", "").startswith("2026-08-10T09:00:00"), (
        "acknowledged_at must be stamped with the current logical instant, got "
        f"{acknowledged.get('acknowledged_at')!r}"
    )

    repeat = api.acknowledge_team_assignment(seat["id"], lead_headers)
    validate_error(repeat, "ERR_ASSIGNMENT_STATE_INVALID")

    after = read_assignment(seat["id"])
    assert_state(after, "ACKNOWLEDGED", "TeamAssignment")
    assert_unchanged(acknowledged, after, ["acknowledged_at", "stood_down_at"])
    assert_no_write(acknowledged, after, "TeamAssignment")
    assert_ledger(read_member(lead_id), "active_assignment_count", 1)


def test_activation_without_an_escalated_signal_is_refused(api):
    """PRD §3.3: "The incident must have at least one signal in `ESCALATED`,
    otherwise no provisional tier could be derived and the request is refused with
    `ERR_NO_ESCALATED_SIGNAL` (HTTP 422)."

    Design: Corner/state_machines/corner_incident_activation_without_escalated_signal_rejected
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-10T09:00:00Z",
        scenario_code="REGULATORY_PROBE",
        title="Single reporter enquiry",
    )
    incident_id = scenario["incident"]["id"]
    lead_headers = scenario["headers"]["lead"]

    signal = record_signal(
        scenario["channel"]["id"],
        scenario["headers"]["listener"],
        headline="Reporter emails a question list",
        reach_score=55,
    )
    link_signal(signal["id"], incident_id, scenario["headers"]["listener"])
    seat_member(incident_id, scenario["ids"]["lead"], "INCIDENT_LEAD", lead_headers)

    response = api.activate_incident(incident_id, lead_headers)
    validate_error(response, "ERR_NO_ESCALATED_SIGNAL")

    incident = read_incident(incident_id)
    assert_fields(
        incident,
        {
            "response_state": "MONITORING",
            "activated_at": None,
            "severity_tier": None,
            "holding_statement_due_at": None,
        },
        "Incident",
    )
    assert_ledger(incident, "escalated_signal_count", 0)
    assert_ledger(incident, "linked_signal_count", 1)
    assert_state(read_signal(signal["id"]), "LINKED", "IssueSignal")


def test_activation_applies_every_declared_side_effect(api):
    """PRD §3.3: "Activation moves the incident `MONITORING → ACTIVATED` and is the
    moment the crisis clock starts ... `holding_statement_due_at` is `activated_at`
    plus the service-level window belonging to the current `severity_tier`: half an
    hour for `SEV1`, one hour for `SEV2`, three hours for `SEV3`, and eight hours
    for `SEV4` ... a base score of 52.50 sits in `LOW`, takes the 0.05 rate, and
    yields a total of 55.13 — a figure that falls inside the `MEDIUM` band while
    keeping the `LOW` rate."

    Design: Corner/state_machines/corner_incident_activation_side_effects_all_applied
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-10T09:00:00Z", title="Regional distribution delay"
    )
    incident_id = scenario["incident"]["id"]
    lead_headers = scenario["headers"]["lead"]

    signal = record_signal(
        scenario["channel"]["id"],
        scenario["headers"]["listener"],
        headline="Local paper covers empty shelves",
        reach_score=75,
    )
    link_signal(signal["id"], incident_id, scenario["headers"]["listener"])
    escalate_signal(signal["id"], scenario["headers"]["listener"])
    seat_member(incident_id, scenario["ids"]["lead"], "INCIDENT_LEAD", lead_headers)
    version_before = incident_version(incident_id)

    incident = validate_success(api.activate_incident(incident_id, lead_headers))

    assert_field(incident, "response_state", "ACTIVATED", "Incident")
    assert incident.get("activated_at", "").startswith("2026-08-10T09:00:00"), (
        "activated_at must be stamped with the current logical instant, got "
        f"{incident.get('activated_at')!r}"
    )
    assert_severity(incident, "SEV2", 83.00, "PROVISIONAL")
    assert incident.get("holding_statement_due_at", "").startswith(
        "2026-08-10T10:00:00"
    ), (
        "the SEV2 holding deadline is activated_at plus one hour, got "
        f"{incident.get('holding_statement_due_at')!r}"
    )
    assert_containment(incident, 52.50, 0.05, 55.13)
    assert_posture(incident, "OPEN")
    assert_field(incident, "sla_breached", False, "Incident")
    assert_ledger(incident, "escalated_signal_count", 1)
    assert_ledger(incident, "linked_signal_count", 1)
    assert incident["version"] == version_before + 1, (
        "activation must increment the incident version by exactly 1: "
        f"{version_before} -> {incident['version']}"
    )


def test_resolving_a_never_activated_incident_is_refused(api):
    """PRD §3.9: "An incident that was never activated cannot be resolved:
    attempting it from `MONITORING` is a declared rejection with
    `ERR_INCIDENT_NOT_ACTIVATED` (HTTP 409) and no state change."

    Design: Corner/state_machines/corner_incident_resolve_from_monitoring_rejected
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-10T09:00:00Z",
        scenario_code="EXEC_MISCONDUCT",
        title="Chatter about a merger",
    )
    incident_id = scenario["incident"]["id"]
    lead_headers = scenario["headers"]["lead"]
    before = read_incident(incident_id)

    response = api.resolve_incident(
        incident_id, lead_headers, resolve_incident_payload(70.00)
    )
    validate_error(response, "ERR_INCIDENT_NOT_ACTIVATED")

    after = read_incident(incident_id)
    assert_fields(
        after,
        {
            "response_state": "MONITORING",
            "resolved_at": None,
            "reputation_index_after": None,
            "final_severity_tier": None,
            "final_severity_score": None,
        },
        "Incident",
    )
    assert_no_write(before, after, "Incident")

    rows, meta = validate_paginated(
        api.list_post_crisis_reviews(lead_headers, {"incident_id": incident_id})
    )
    assert meta["total_count"] == 0, (
        "a refused resolution opens no retrospective, found "
        f"{meta['total_count']}"
    )
    assert rows == [], f"expected no post-crisis review, got {rows}"


def test_withdrawn_statement_accepts_no_further_transition(api):
    """PRD §3.5: "Submitting for review advances the statement into `IN_REVIEW` and
    is accepted from either `DRAFT` or `REVISION_REQUESTED`; from any other state
    the answer is `ERR_STATEMENT_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/corner_statement_withdrawn_terminal_state_blocks_further_transitions
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", title="Depot fire aftermath"
    )
    comms_headers = scenario["headers"]["comms"]
    statement = draft_statement(
        scenario,
        statement_type="HOLDING",
        body="Emergency services have cleared the site.",
    )
    withdrawn = get_success_data(
        api.withdraw_statement(
            statement["id"],
            withdraw_statement_payload(
                withdraw_reason="Superseded by an all-clear announcement."
            ),
            comms_headers,
        )
    )
    assert_state(withdrawn, "WITHDRAWN", "Statement")

    validate_error(
        api.submit_statement_review(statement["id"], comms_headers),
        "ERR_STATEMENT_STATE_INVALID",
    )
    validate_error(
        api.publish_statement(statement["id"], comms_headers),
        "ERR_STATEMENT_STATE_INVALID",
    )

    after = read_statement(statement["id"])
    assert_fields(
        after,
        {
            "state": "WITHDRAWN",
            "submitted_at": None,
            "published_at": None,
            "review_deadline_at": None,
            "approved_at": None,
        },
        "Statement",
    )
    assert_ledger(read_incident(scenario["incident"]["id"]), "open_approval_task_count", 0)


def test_exhausted_revision_budget_closes_the_review_cycle(api):
    """PRD §3.5: "The revision budget is three rounds: `revision_locked` must be
    false and `revision_round` must be strictly less than 3, or the request is
    refused with `ERR_REVISION_LIMIT_REACHED` (HTTP 409) ... `revision_locked`
    latches to true the moment `revision_round` reaches 3 ... The full cycle is
    therefore `DRAFT → IN_REVIEW → REVISION_REQUESTED → DRAFT → IN_REVIEW` and so
    on, bounded at a `revision_round` of 3", and "a statement whose revision budget
    is exhausted is refused with `ERR_REVISION_LIMIT_REACHED` (HTTP 409)."

    Design: Corner/state_machines/corner_statement_revision_limit_terminates_cycle_rejected
    """
    scenario = setup_statement_in_review(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        body="Round zero draft.",
    )
    statement_id = scenario["statement"]["id"]
    comms_headers = scenario["headers"]["comms"]

    for round_index, body in enumerate(
        ("Round one draft.", "Round two draft.", "Round three draft."), start=1
    ):
        pending = tasks_for_statement(statement_id, state="PENDING")
        assert pending, (
            f"round {round_index - 1} must fan out at least one PENDING task"
        )
        decide_task(pending[0], "REJECT", f"Round {round_index - 1} rejected.")
        assert_state(read_statement(statement_id), "REVISION_REQUESTED", "Statement")

        revised = validate_success(
            api.revise_statement(
                statement_id, revise_statement_payload(body=body), comms_headers
            )
        )
        assert_state(revised, "DRAFT", "Statement")
        assert_field(revised, "revision_round", round_index, "Statement")
        assert_field(revised, "body", body, "Statement")
        assert_field(
            revised, "revision_locked", round_index == 3, "Statement"
        )
        if round_index < 3:
            submit_for_review(scenario, statement_id)

    locked = read_statement(statement_id)
    response = api.submit_statement_review(statement_id, comms_headers)
    validate_error(response, "ERR_REVISION_LIMIT_REACHED")

    after = read_statement(statement_id)
    assert_fields(
        after,
        {
            "state": "DRAFT",
            "revision_round": 3,
            "revision_locked": True,
            "body": "Round three draft.",
        },
        "Statement",
    )
    assert_no_write(locked, after, "Statement")
    assert tasks_for_statement(statement_id, state="PENDING") == [], (
        "the refused submission must fan out no approval task"
    )
    assert_ledger(
        read_incident(scenario["incident"]["id"]), "open_approval_task_count", 0
    )


def test_notice_blocked_by_a_rejection_returns_to_queued_on_later_approval(api):
    """PRD §3.6: "The two system-driven notice movements complete the picture, and
    they are symmetric: a `QUEUED` notice transitions to `BLOCKED` when the
    statement it carries is pushed into `REVISION_REQUESTED`, recomputing
    `blocked_notice_count` and driving the posture to `RESTRICTED`; and a `BLOCKED`
    notice returns to `QUEUED` when that same statement is approved again in a
    later revision round, again recomputing `blocked_notice_count` and the
    posture."

    Design: Corner/state_machines/corner_notice_blocked_then_requeued_when_statement_approved_later_round
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", title="Recall widens to a second batch"
    )
    incident_id = scenario["incident"]["id"]
    comms_headers = scenario["headers"]["comms"]

    statement = draft_statement(
        scenario,
        statement_type="HOLDING",
        body="We are reviewing the affected batch today.",
    )
    notice = queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1000)
    assert_state(notice, "QUEUED", "StakeholderNotice")
    submit_for_review(scenario)

    first_round = tasks_for_statement(statement["id"], state="PENDING")
    assert first_round, "the first review round must fan out at least one task"
    decide_task(first_round[0], "REJECT", "Soften the tone.")

    assert_state(read_statement(statement["id"]), "REVISION_REQUESTED", "Statement")
    assert_state(read_notice(notice["id"]), "BLOCKED", "StakeholderNotice")
    restricted = read_incident(incident_id)
    assert_ledger(restricted, "blocked_notice_count", 1)
    assert_posture(restricted, "RESTRICTED")

    validate_success(
        api.revise_statement(
            statement["id"],
            revise_statement_payload(
                body="We are reviewing the affected batch and will publish results."
            ),
            comms_headers,
        )
    )
    submit_for_review(scenario)
    approved = approve_to_quorum(scenario)

    assert_state(approved, "APPROVED", "Statement")
    assert_field(approved, "revision_round", 1, "Statement")
    requeued = read_notice(notice["id"])
    assert_state(requeued, "QUEUED", "StakeholderNotice")
    assert_field(requeued, "released_at", None, "StakeholderNotice")
    relaxed = read_incident(incident_id)
    assert_ledger(relaxed, "blocked_notice_count", 0)
    assert_posture(relaxed, "OPEN")


def test_stale_material_restarts_the_decay_curve_when_reviewed_again(api):
    """PRD §3.1: "sixteen whole days after review the score is 60.00 and the
    material is still `READY`, because the threshold is inclusive; on the
    seventeenth day the score is 57.50 and the state becomes `STALE`. Re-reviewing
    a `STALE` asset restarts the curve at 100.00 and returns it to `READY`, so the
    cycle between `READY` and `STALE` may repeat indefinitely."

    Design: Corner/state_machines/corner_material_stale_then_reviewed_restarts_the_decay_curve
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-01T00:00:00Z",
        scenario_code="DATA_BREACH",
        title="Phishing wave against staff",
    )
    comms_headers = scenario["headers"]["comms"]
    material = file_material(
        comms_headers,
        scenario_code="DATA_BREACH",
        material_type="FAQ",
        title="Breach FAQ for the support desk",
    )
    ready = review_material(
        material["id"], comms_headers, reviewer_notes="First review at the epoch clock."
    )
    assert_field(ready, "readiness_state", "READY", "PreparedMaterial")
    assert_two_decimals(ready.get("readiness_score"), 100.00, "readiness_score")

    set_clock("2026-08-18T00:00:00Z")
    run_sla_sweep(scenario)

    stale = read_material(material["id"])
    assert_field(stale, "readiness_state", "STALE", "PreparedMaterial")
    assert_two_decimals(stale.get("readiness_score"), 57.50, "readiness_score")

    refreshed = validate_success(
        api.review_prepared_material(
            material["id"],
            material_review_payload(
                reviewer_notes="Re-reviewed after the checkpoint flagged it stale."
            ),
            comms_headers,
        )
    )
    assert_field(refreshed, "readiness_state", "READY", "PreparedMaterial")
    assert_two_decimals(refreshed.get("readiness_score"), 100.00, "readiness_score")
    assert_field(
        refreshed,
        "reviewer_notes",
        "Re-reviewed after the checkpoint flagged it stale.",
        "PreparedMaterial",
    )
    assert refreshed.get("last_reviewed_at", "").startswith("2026-08-18T00:00:00"), (
        "the re-review must stamp last_reviewed_at with the current instant, got "
        f"{refreshed.get('last_reviewed_at')!r}"
    )
