"""Error-catalogue behaviour: per-resource not-found identifiers, the pinned
order of rejection, and state-gate refusals that must leave their target
untouched (PRD §2.2, §2.5, §2.9, §5)."""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_field,
    assert_ledger,
    assert_no_write,
    assert_posture,
    assert_severity,
    assert_state,
    assert_two_decimals,
    assert_four_decimals,
    assert_unchanged,
    book_interview,
    cancel_interview_payload,
    cancel_notice,
    channel_version,
    confirm_interview_payload,
    decide_payload,
    draft_statement,
    escalate_signal,
    file_material,
    incident_version,
    issue_correction_payload,
    link_signal,
    link_signal_payload,
    log_claim,
    make_comms_lead_headers,
    make_program_admin_headers,
    material_review_payload,
    queue_notice,
    read_channel,
    read_claim,
    read_incident,
    read_interview,
    read_material,
    read_member,
    read_notice,
    read_review,
    read_signal,
    read_statement,
    read_task,
    record_signal,
    register_member,
    resolve_incident,
    review_material,
    score_review,
    score_review_payload,
    seat_member,
    set_clock,
    setup_activated_incident,
    setup_monitoring_incident,
    setup_published_statement,
    setup_triaged_claim,
    statement_payload,
    submit_for_review,
    tasks_for_statement,
    triage_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Per-resource existence errors (PRD §2.5)
# ---------------------------------------------------------------------------


def test_unknown_registry_ids_return_entity_specific_not_found(api, program_admin_headers):
    """PRD §2.5: "an identifier that does not resolve produces the
    resource-specific not-found error at HTTP 404 — `ERR_TEAM_MEMBER_NOT_FOUND`,
    `ERR_CHANNEL_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_SIGNAL_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`,
    `ERR_APPROVAL_TASK_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`"

    Design: Corner/errors/corner_error_unknown_registry_ids_return_entity_specific_not_found
    """
    reads = [
        (api.get_monitored_channel(NON_EXISTENT_UUID, program_admin_headers),
         "ERR_CHANNEL_NOT_FOUND"),
        (api.get_team_assignment(NON_EXISTENT_UUID, program_admin_headers),
         "ERR_ASSIGNMENT_NOT_FOUND"),
        (api.get_approval_task(NON_EXISTENT_UUID, program_admin_headers),
         "ERR_APPROVAL_TASK_NOT_FOUND"),
        (api.get_stakeholder_notice(NON_EXISTENT_UUID, program_admin_headers),
         "ERR_NOTICE_NOT_FOUND"),
    ]
    for response, expected_error_id in reads:
        # validate_error cross-checks the declared HTTP status of PRD §5 and
        # requires a non-empty human-readable message (PRD §2.2).
        validate_error(response, expected_error_id)
        body = response.json()
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
            f"{expected_error_id} response is missing meta.api_request_id"
        )
        assert meta["api_request_id"].startswith("req_"), (
            f"meta.api_request_id must start with req_, got {meta['api_request_id']!r}"
        )
        assert isinstance(meta.get("api_request_timestamp"), str) and meta[
            "api_request_timestamp"
        ], f"{expected_error_id} response is missing meta.api_request_timestamp"


def test_unknown_readiness_and_closure_ids_return_not_found(api, program_admin_headers):
    """PRD §2.5: "Path identifiers are resolved left to right before any body
    field is inspected, and an identifier that does not resolve produces the
    resource-specific not-found error at HTTP 404"

    Design: Corner/errors/corner_error_unknown_readiness_and_closure_ids_return_not_found
    """
    reads = [
        (api.get_prepared_material(NON_EXISTENT_UUID, program_admin_headers),
         "ERR_MATERIAL_NOT_FOUND"),
        (api.get_media_interview(NON_EXISTENT_UUID, program_admin_headers),
         "ERR_INTERVIEW_NOT_FOUND"),
        (api.get_misinformation_claim(NON_EXISTENT_UUID, program_admin_headers),
         "ERR_CLAIM_NOT_FOUND"),
        (api.get_post_crisis_review(NON_EXISTENT_UUID, program_admin_headers),
         "ERR_REVIEW_NOT_FOUND"),
    ]
    for response, expected_error_id in reads:
        validate_error(response, expected_error_id)
        body = response.json()
        # These are single-resource reads, so the error envelope carries no row
        # list and, per PRD §2.2, no pagination fields at all.
        assert not isinstance(body["data"], list), (
            f"{expected_error_id} response returned a data array"
        )
        for pagination_field in ("limit", "offset", "total_count", "has_more"):
            assert pagination_field not in body["meta"], (
                f"error meta must not carry {pagination_field}"
            )


# ---------------------------------------------------------------------------
# The signal state gate (PRD §3.2)
# ---------------------------------------------------------------------------


def test_signal_state_gate_precedes_the_escalation_threshold(api):
    """PRD §3.2: "An `OPEN` signal can never be escalated — the unlinked case is
    a declared rejection, not a shortcut, and it produces
    `ERR_INVALID_SIGNAL_STATE` (HTTP 409) with no state change whatsoever."
    "Attempting to link a signal that is not `OPEN` is refused with
    `ERR_INVALID_SIGNAL_STATE` (HTTP 409)"

    Design: Corner/errors/corner_error_signal_state_gate_precedes_the_escalation_threshold
    """
    scenario = setup_monitoring_incident(clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    listener = scenario["headers"]["listener"]

    # A MEDIA channel, credibility tier A and neutral sentiment: 55 * 1.00 + 8
    # freezes the score at 63.00, below the 70.00 escalation floor (PRD §3.2).
    signal = record_signal(scenario["channel"]["id"], listener, reach_score=55)
    assert_two_decimals(signal["escalation_score"], 63.00, "escalation_score")
    assert_state(signal, "OPEN", "signal")

    before = read_signal(signal["id"])
    response = api.escalate_issue_signal(signal["id"], listener)
    validate_error(response, "ERR_INVALID_SIGNAL_STATE")
    after = read_signal(signal["id"])
    assert_no_write(before, after, "signal")
    assert_state(after, "OPEN", "signal")
    assert_field(after, "escalated_at", None, "signal")

    linked = validate_success(
        api.link_issue_signal(signal["id"], link_signal_payload(incident_id), listener)
    )
    assert_state(linked, "LINKED", "signal")

    before = read_signal(signal["id"])
    incident_before = read_incident(incident_id)
    response = api.link_issue_signal(
        signal["id"], link_signal_payload(incident_id), listener
    )
    validate_error(response, "ERR_INVALID_SIGNAL_STATE")
    after = read_signal(signal["id"])
    assert_no_write(before, after, "signal")
    assert_state(after, "LINKED", "signal")

    incident_after = read_incident(incident_id)
    assert_no_write(incident_before, incident_after, "incident")
    assert_ledger(incident_after, "linked_signal_count", 1)


# ---------------------------------------------------------------------------
# RESOLVED is a closed book (PRD §3.5, §2.9)
# ---------------------------------------------------------------------------


def test_resolved_incident_refuses_new_statement_drafts(api):
    """PRD §3.5: "The incident must be `ACTIVATED` — drafting against a
    still-`MONITORING` file yields `ERR_INCIDENT_NOT_ACTIVATED`, and against a
    `RESOLVED` one `ERR_INCIDENT_ALREADY_RESOLVED`"

    Design: Corner/errors/corner_error_resolved_incident_refuses_new_statement_drafts
    """
    scenario = setup_activated_incident(tier="SEV2", clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    resolve_incident(scenario, reputation_index_after=84.00)

    incident_before = read_incident(incident_id)
    assert_field(incident_before, "response_state", "RESOLVED", "incident")
    # A RESOLVED response forces the highest-precedence posture rule (PRD §2.6),
    # yet the response-dimension check of PRD §2.9 answers before the posture.
    assert_posture(incident_before, "FROZEN")

    current_version = incident_version(incident_id)
    response = api.create_statement(
        statement_payload(
            incident_id,
            current_version,
            statement_type="UPDATE",
            body="A late addition nobody asked for.",
        ),
        scenario["headers"]["comms"],
    )
    validate_error(response, "ERR_INCIDENT_ALREADY_RESOLVED")

    rows, meta = validate_paginated(
        api.list_statements(make_program_admin_headers(), {"incident_id": incident_id})
    )
    assert meta["total_count"] == 0, "the refused draft was persisted"
    assert rows == [], "the refused draft was persisted"

    incident_after = read_incident(incident_id)
    assert_no_write(incident_before, incident_after, "incident")
    assert_field(incident_after, "response_state", "RESOLVED", "incident")


# ---------------------------------------------------------------------------
# Segregation of duties (PRD §3.5, §2.10)
# ---------------------------------------------------------------------------


def test_segregation_of_duties_when_the_drafter_holds_the_only_seat(api):
    """PRD §3.5: "One subtlety is deliberate: the drafter is **not** filtered out
    of the candidate pool. If the only `ACKNOWLEDGED` holder of a required seat
    happens to be the statement's `drafted_by_member_id`, the task is still
    created and assigned to that member, and the segregation-of-duties refusal
    surfaces later, when they try to decide it."

    Design: Corner/errors/corner_error_segregation_of_duties_when_the_drafter_holds_the_only_seat
    """
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        seat_roles=["INCIDENT_LEAD", "LEGAL_COUNSEL"],
    )
    incident_id = scenario["incident"]["id"]
    lead_id = scenario["ids"]["lead"]

    # The member holding the only ACKNOWLEDGED INCIDENT_LEAD seat also drafts,
    # acting in the CommsLead role, so drafted_by_member_id is pinned to them.
    scenario["headers"]["lead_as_comms"] = make_comms_lead_headers(lead_id)
    statement = draft_statement(scenario, statement_type="HOLDING", drafter="lead_as_comms")
    assert_field(statement, "drafted_by_member_id", lead_id, "statement")

    submit_for_review(scenario)
    tasks = tasks_for_statement(statement["id"])
    assert [task["required_team_role"] for task in tasks] == [
        "INCIDENT_LEAD",
        "LEGAL_COUNSEL",
    ], "the quorum tasks were not created in the pinned seat order"
    lead_task = tasks[0]
    assert_field(lead_task, "assignee_member_id", lead_id, "approval task")
    assert_state(lead_task, "PENDING", "approval task")

    before = read_task(lead_task["id"])
    response = api.decide_approval_task(
        lead_task["id"],
        decide_payload("APPROVE", "I wrote it, I like it."),
        scenario["headers"]["lead"],
    )
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES")

    after = read_task(lead_task["id"])
    assert_no_write(before, after, "approval task")
    assert_state(after, "PENDING", "approval task")
    assert_field(after, "decided_at", None, "approval task")

    statement_after = read_statement(statement["id"])
    assert_state(statement_after, "IN_REVIEW", "statement")
    assert_field(statement_after, "approvals_recorded", 0, "statement")
    assert_ledger(read_incident(incident_id), "open_approval_task_count", 2)


# ---------------------------------------------------------------------------
# Notice, claim, interview, material and review state gates (PRD §2.9 step 10)
# ---------------------------------------------------------------------------


def test_release_after_cancel_reports_notice_state_before_publication(api):
    """PRD §3.6: "The notice must be `QUEUED`, or `ERR_NOTICE_STATE_INVALID`
    (HTTP 409)."

    Design: Corner/errors/corner_error_release_after_cancel_reports_notice_state_before_publication
    """
    scenario = setup_activated_incident(tier="SEV2", clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    statement = draft_statement(scenario, statement_type="HOLDING")
    notice = queue_notice(scenario, audience="EMPLOYEE", estimated_reach=4000)
    cancelled = cancel_notice(
        scenario, notice["id"], cancel_reason="Superseded by an all-hands briefing."
    )
    assert_state(cancelled, "CANCELLED", "notice")

    before = read_notice(notice["id"])
    response = api.release_stakeholder_notice(notice["id"], scenario["headers"]["comms"])
    # The notice's own state answers at PRD §2.9 step 10, ahead of the
    # unpublished statement it carries at step 16.
    validate_error(response, "ERR_NOTICE_STATE_INVALID")

    after = read_notice(notice["id"])
    assert_no_write(before, after, "notice")
    assert_state(after, "CANCELLED", "notice")
    assert_field(after, "released_at", None, "notice")

    incident = read_incident(incident_id)
    assert_ledger(incident, "released_notice_count", 0)
    assert_two_decimals(
        incident["stakeholder_reach_index"], 0.00, "stakeholder_reach_index"
    )
    assert_state(read_statement(statement["id"]), "DRAFT", "statement")


def test_second_triage_reports_claim_state_invalid(api):
    """PRD §3.8: "It advances `DETECTED → TRIAGED`, refusing anything else with
    `ERR_CLAIM_STATE_INVALID` (HTTP 409)"

    Design: Corner/errors/corner_error_second_triage_reports_claim_state_invalid
    """
    scenario = setup_triaged_claim(
        tier="SEV2", clock="2026-08-10T09:00:00Z", virality_score=45.00
    )
    claim_id = scenario["claim"]["id"]
    assert_state(scenario["claim"], "TRIAGED", "claim")

    before = read_claim(claim_id)
    response = api.triage_misinformation_claim(claim_id, scenario["headers"]["listener"])
    validate_error(response, "ERR_CLAIM_STATE_INVALID")

    after = read_claim(claim_id)
    assert_no_write(before, after, "claim")
    assert_state(after, "TRIAGED", "claim")
    assert_field(after, "resolution_branch", None, "claim")
    assert_field(after, "takedown_confirmed", False, "claim")
    assert_field(after, "corrected", False, "claim")
    assert_ledger(read_incident(scenario["incident"]["id"]), "open_claim_count", 1)


def test_confirm_after_cancel_reports_interview_state_invalid(api):
    """PRD §3.7: "The interview must be in `SCHEDULED`, or
    `ERR_INTERVIEW_STATE_INVALID` (HTTP 409)."

    Design: Corner/errors/corner_error_confirm_after_cancel_reports_interview_state_invalid
    """
    scenario = setup_activated_incident(tier="SEV2", clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    spox_id = scenario["ids"]["spox"]
    assert_posture(read_incident(incident_id), "OPEN")

    interview = book_interview(
        scenario,
        "2026-08-12T10:00:00Z",
        "2026-08-12T10:45:00Z",
        anticipated_question_count=8,
    )
    cancelled = validate_success(
        api.cancel_media_interview(
            interview["id"],
            cancel_interview_payload(cancel_reason="Outlet withdrew the slot."),
            scenario["headers"]["comms"],
        )
    )
    assert_state(cancelled, "CANCELLED", "interview")

    before = read_interview(interview["id"])
    response = api.confirm_media_interview(
        interview["id"], scenario["headers"]["comms"], confirm_interview_payload(3)
    )
    validate_error(response, "ERR_INTERVIEW_STATE_INVALID")

    after = read_interview(interview["id"])
    assert_no_write(before, after, "interview")
    assert_state(after, "CANCELLED", "interview")
    assert_field(after, "confirmed_at", None, "interview")
    assert_field(after, "high_risk_answers_approved_count", 0, "interview")
    assert_ledger(read_member(spox_id), "scheduled_interview_minutes", 0)
    assert_ledger(read_incident(incident_id), "confirmed_interview_count", 0)


def test_reviewing_a_ready_material_reports_material_state_invalid(api):
    """PRD §3.1: "A content review by the communications lead — permitted from
    `readiness_state` `DRAFT` or `STALE`, and refused with
    `ERR_MATERIAL_STATE_INVALID` otherwise — stamps `last_reviewed_at` with the
    current instant, records the supplied `reviewer_notes`, and resets
    `readiness_score` to exactly 100.00, which lands the material in `READY`."

    Design: Corner/errors/corner_error_reviewing_a_ready_material_reports_material_state_invalid
    """
    set_clock("2026-08-01T00:00:00Z")
    comms = register_member(full_name="Ivo Berg", org_title="Comms Director")
    comms_headers = make_comms_lead_headers(comms["id"])

    material = file_material(
        scenario_code="DATA_BREACH",
        material_type="DARK_SITE_PAGE",
        title="Breach dark site",
        dark_site_url="https://dark.example/breach",
    )
    reviewed = review_material(
        material["id"], comms_headers, reviewer_notes="Copy and contacts checked."
    )
    assert_field(reviewed, "readiness_state", "READY", "material")
    assert_two_decimals(reviewed["readiness_score"], 100.00, "readiness_score")

    # Four whole days later the score has decayed by 4 * 2.50 to 90.00, which is
    # still at or above the 60.00 floor, so the material remains READY and the
    # review transition is therefore still inadmissible (PRD §3.1).
    set_clock("2026-08-05T00:00:00Z")
    before = read_material(material["id"])
    assert_field(before, "readiness_state", "READY", "material")

    response = api.review_prepared_material(
        material["id"],
        material_review_payload(reviewer_notes="Just topping up the freshness."),
        comms_headers,
    )
    validate_error(response, "ERR_MATERIAL_STATE_INVALID")

    after = read_material(material["id"])
    assert_unchanged(
        before, after, ["readiness_state", "last_reviewed_at", "reviewer_notes"]
    )
    assert_field(after, "readiness_state", "READY", "material")
    assert_field(after, "reviewer_notes", "Copy and contacts checked.", "material")
    assert after["last_reviewed_at"] == reviewed["last_reviewed_at"], (
        "the refused review re-stamped last_reviewed_at and restarted the decay curve"
    )


# ---------------------------------------------------------------------------
# Seat dependency at activation (PRD §3.3, §2.9 step 15)
# ---------------------------------------------------------------------------


def test_activation_requires_an_acknowledged_incident_lead_seat(api):
    """PRD §3.3: "A seat with `team_role` `INCIDENT_LEAD` must exist on the
    incident in state `ACKNOWLEDGED`, otherwise `ERR_ASSIGNMENT_NOT_ACKNOWLEDGED`
    (HTTP 409)." "`holding_statement_due_at` is `activated_at` plus the
    service-level window belonging to the current `severity_tier`: half an hour
    for `SEV1`, one hour for `SEV2`"

    Design: Corner/errors/corner_error_activation_requires_an_acknowledged_incident_lead_seat
    """
    scenario = setup_monitoring_incident(clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    lead_headers = scenario["headers"]["lead"]

    # 75 * 1.00 + 8 = 83.00 clears the 70.00 escalation floor, so the incident
    # already carries an ESCALATED signal and bands SEV2 at activation.
    signal = record_signal(
        scenario["channel"]["id"], scenario["headers"]["listener"], reach_score=75
    )
    link_signal(signal["id"], incident_id, scenario["headers"]["listener"])
    escalated = escalate_signal(signal["id"], scenario["headers"]["listener"])
    assert_state(escalated, "ESCALATED", "signal")
    assert_two_decimals(escalated["escalation_score"], 83.00, "escalation_score")

    assignment = seat_member(
        incident_id,
        scenario["ids"]["lead"],
        "INCIDENT_LEAD",
        lead_headers,
        acknowledge=False,
    )
    assert_state(assignment, "ASSIGNED", "assignment")

    before = read_incident(incident_id)
    response = api.activate_incident(incident_id, lead_headers)
    validate_error(response, "ERR_ASSIGNMENT_NOT_ACKNOWLEDGED")

    after = read_incident(incident_id)
    assert_no_write(before, after, "incident")
    assert_field(after, "response_state", "MONITORING", "incident")
    assert_field(after, "activated_at", None, "incident")
    assert_field(after, "holding_statement_due_at", None, "incident")

    acknowledged = validate_success(
        api.acknowledge_team_assignment(assignment["id"], lead_headers)
    )
    assert_state(acknowledged, "ACKNOWLEDGED", "assignment")

    activated = validate_success(api.activate_incident(incident_id, lead_headers))
    assert_field(activated, "response_state", "ACTIVATED", "incident")
    assert_field(activated, "activated_at", "2026-08-10T09:00:00.000Z", "incident")
    assert_field(
        activated, "holding_statement_due_at", "2026-08-10T10:00:00.000Z", "incident"
    )
    assert_severity(activated, "SEV2", 83.00, "PROVISIONAL")


# ---------------------------------------------------------------------------
# The correction fork's referential gate (PRD §3.8, §2.9 step 17)
# ---------------------------------------------------------------------------


def test_correction_requires_a_published_correction_statement(api):
    """PRD §3.8: "The referenced statement must exist and must simultaneously
    have `statement_type` `CORRECTION`, be in state `PUBLISHED`, and belong to the
    same incident as the claim; any of those failing gives
    `ERR_CORRECTION_STATEMENT_REQUIRED` (HTTP 409)."

    Design: Corner/errors/corner_error_correction_requires_a_published_correction_statement
    """
    scenario = setup_published_statement(
        statement_type="HOLDING", tier="SEV2", clock="2026-08-10T09:00:00Z"
    )
    holding = scenario["statement"]
    assert_state(holding, "PUBLISHED", "statement")
    assert_field(holding, "statement_type", "HOLDING", "statement")

    channel_id = scenario["channel"]["id"]
    claim = log_claim(scenario, virality_score=40.00, channel_id=channel_id)
    triage_claim(scenario)

    claim_before = read_claim(claim["id"])
    channel_before = read_channel(channel_id)
    # The channel version travels current, so the optimistic-concurrency check of
    # PRD §2.9 step 9 passes and only the referential gate can refuse.
    response = api.issue_correction(
        claim["id"],
        issue_correction_payload(
            holding["id"],
            "2026-08-10T11:00:00Z",
            "2026-08-10T11:30:00Z",
            channel_version(channel_id),
        ),
        scenario["headers"]["comms"],
    )
    validate_error(response, "ERR_CORRECTION_STATEMENT_REQUIRED")

    claim_after = read_claim(claim["id"])
    assert_no_write(claim_before, claim_after, "claim")
    assert_state(claim_after, "TRIAGED", "claim")
    assert_field(claim_after, "correction_statement_id", None, "claim")
    assert_field(claim_after, "correction_window_minutes", 0, "claim")

    channel_after = read_channel(channel_id)
    assert_no_write(channel_before, channel_after, "channel")
    assert_ledger(channel_after, "reserved_correction_minutes", 0)
    assert_state(read_statement(holding["id"]), "PUBLISHED", "statement")


# ---------------------------------------------------------------------------
# The interview preparation conjunction (PRD §3.7)
# ---------------------------------------------------------------------------


def test_question_pack_floor_blocks_confirmation_from_both_sides(api):
    """PRD §3.7: "The preparation pack must be complete, meaning
    `anticipated_question_count` is at least 8 and
    `high_risk_answers_approved_count` is at least 3; failure gives
    `ERR_QUESTION_PACK_INCOMPLETE` (HTTP 422)."

    Design: Corner/errors/corner_error_question_pack_floor_blocks_confirmation_from_both_sides
    """
    scenario = setup_activated_incident(tier="SEV2", clock="2026-08-10T09:00:00Z")
    incident_id = scenario["incident"]["id"]
    spox_id = scenario["ids"]["spox"]
    comms = scenario["headers"]["comms"]

    # Two bookings separated by more than the thirty-minute preparation buffer.
    interview_a = book_interview(
        scenario,
        "2026-08-12T10:00:00Z",
        "2026-08-12T10:45:00Z",
        anticipated_question_count=8,
    )
    interview_b = book_interview(
        scenario,
        "2026-08-12T14:00:00Z",
        "2026-08-12T14:45:00Z",
        anticipated_question_count=6,
    )

    a_before = read_interview(interview_a["id"])
    b_before = read_interview(interview_b["id"])

    # Eight anticipated questions but only two approved high-risk answers.
    validate_error(
        api.confirm_media_interview(
            interview_a["id"], comms, confirm_interview_payload(2)
        ),
        "ERR_QUESTION_PACK_INCOMPLETE",
    )
    # Three approved high-risk answers but only six anticipated questions.
    validate_error(
        api.confirm_media_interview(
            interview_b["id"], comms, confirm_interview_payload(3)
        ),
        "ERR_QUESTION_PACK_INCOMPLETE",
    )

    a_after = read_interview(interview_a["id"])
    b_after = read_interview(interview_b["id"])
    assert_no_write(a_before, a_after, "interview A")
    assert_no_write(b_before, b_after, "interview B")
    assert_state(a_after, "SCHEDULED", "interview A")
    assert_state(b_after, "SCHEDULED", "interview B")
    assert_field(a_after, "confirmed_at", None, "interview A")
    assert_field(b_after, "confirmed_at", None, "interview B")
    assert_ledger(read_member(spox_id), "scheduled_interview_minutes", 0)
    assert_ledger(read_incident(incident_id), "confirmed_interview_count", 0)

    # Both floors satisfied: the same booking now confirms.
    confirmed = validate_success(
        api.confirm_media_interview(
            interview_a["id"], comms, confirm_interview_payload(3)
        )
    )
    assert_state(confirmed, "CONFIRMED", "interview A")
    assert_field(confirmed, "high_risk_answers_approved_count", 3, "interview A")
    assert_field(confirmed, "confirmed_at", "2026-08-10T09:00:00.000Z", "interview A")
    assert_ledger(read_member(spox_id), "scheduled_interview_minutes", 45)
    assert_ledger(read_incident(incident_id), "confirmed_interview_count", 1)


# ---------------------------------------------------------------------------
# SCORED is terminal for the retrospective (PRD §3.9)
# ---------------------------------------------------------------------------


def test_second_scoring_reports_review_state_invalid(api):
    """PRD §3.9: "The review must be in `OPEN`, or `ERR_REVIEW_STATE_INVALID`
    (HTTP 409), and its incident must be in `RESOLVED`." "`reported_delta` is then
    the raw variant when `scoring_method` is `RAW` and the adjusted variant when
    it is `ADJUSTED`."

    Design: Corner/errors/corner_error_second_scoring_reports_review_state_invalid
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", reputation_index_before=90.00
    )
    incident_id = scenario["incident"]["id"]
    set_clock("2026-08-10T13:00:00Z")
    resolve_incident(scenario, reputation_index_after=82.60)
    review_id = scenario["review"]["id"]
    assert_state(scenario["review"], "OPEN", "review")

    # No released notices, so exposure_factor is 0.0000, and no claims, so the
    # correction ratio is 0.0000 and the efficacy bonus 0.00: the raw delta
    # 82.60 - 90.00 = -7.40 equals the adjusted delta (PRD §3.9).
    scored = score_review(scenario, scoring_method="RAW", playbook_update_count=3)
    assert_state(scored, "SCORED", "review")
    assert_field(scored, "scoring_method", "RAW", "review")
    assert_field(scored, "playbook_update_count", 3, "review")
    assert_field(scored, "scored_at", "2026-08-10T13:00:00.000Z", "review")
    assert_four_decimals(scored["exposure_factor"], 0.0000, "exposure_factor")
    assert_two_decimals(scored["reputation_delta_raw"], -7.40, "reputation_delta_raw")
    assert_two_decimals(
        scored["reputation_delta_adjusted"], -7.40, "reputation_delta_adjusted"
    )
    assert_two_decimals(scored["reported_delta"], -7.40, "reported_delta")

    before = read_review(review_id)
    response = api.score_post_crisis_review(
        review_id,
        score_review_payload(scoring_method="ADJUSTED", playbook_update_count=9),
        scenario["headers"]["exec"],
    )
    validate_error(response, "ERR_REVIEW_STATE_INVALID")

    after = read_review(review_id)
    assert_no_write(before, after, "review")
    assert_state(after, "SCORED", "review")
    assert_field(after, "scoring_method", "RAW", "review")
    assert_field(after, "playbook_update_count", 3, "review")
    assert_two_decimals(after["reported_delta"], -7.40, "reported_delta")
    assert_two_decimals(
        read_incident(incident_id)["reputation_delta_reported"],
        -7.40,
        "reputation_delta_reported",
    )
