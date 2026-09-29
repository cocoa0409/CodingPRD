"""Validation gates: the ordered precondition checks of PRD §2.9 exercised on
both sides of their boundaries.

Every scenario is rebuilt from PRD-declared endpoints inside the test, because
the server starts from an empty database before each one.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    add_published_statement,
    assert_no_write,
    assert_pagination_meta,
    assert_posture,
    assert_privilege,
    assert_privilege_payload,
    assert_two_decimals,
    book_interview,
    cancel_notice,
    channel_version,
    confirm_interview_payload,
    draft_statement,
    incident_payload,
    issue_correction_payload,
    log_claim,
    make_incident_lead_headers,
    make_program_admin_headers,
    media_interview_payload,
    queue_notice,
    read_assignment,
    read_channel,
    read_claim,
    read_incident,
    read_interview,
    read_member,
    read_notice,
    register_channel,
    register_member,
    release_notice_payload,
    resolve_incident_payload,
    seed_roster,
    set_clock,
    setup_activated_incident,
    setup_monitoring_incident,
    setup_published_statement,
    statement_payload,
    team_assignment_payload,
    triage_claim,
    validate_error,
    validate_paginated,
    validate_success,
    verify_channel_path,
)


# ---------------------------------------------------------------------------
# Interview confirmation: all four gates satisfied at once (PRD §3.7)
# ---------------------------------------------------------------------------


def test_interview_confirmation_passes_every_gate_at_the_minima(api):
    """PRD §3.7: "On success `confirmed_at` is stamped, the spokesperson's
    `scheduled_interview_minutes` increases by exactly this interview's
    `duration_minutes`, the incident's `confirmed_interview_count` is
    recomputed, and the incident's `version` is incremented by 1."

    Design: Corner/validations/corner_validation_all_gates_satisfied_confirms_interview
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="PLANT_INCIDENT"
    )
    incident_id = scenario["incident"]["id"]
    spox_id = scenario["ids"]["spox"]

    # Posture is OPEN, the spokesperson's calendar is empty, media training runs
    # to 2026-12-01 and the pack sits at exactly the declared floors.
    assert_posture(read_incident(incident_id), "OPEN")
    interview = book_interview(
        scenario,
        "2026-08-12T14:00:00Z",
        "2026-08-12T15:00:00Z",
        anticipated_question_count=8,
    )
    assert interview["state"] == "SCHEDULED"
    assert interview["duration_minutes"] == 60

    response = api.confirm_media_interview(
        interview["id"],
        scenario["headers"]["comms"],
        confirm_interview_payload(high_risk_answers_approved_count=3),
    )
    confirmed = validate_success(response, 200)

    assert confirmed["state"] == "CONFIRMED"
    assert confirmed["confirmed_at"].startswith("2026-08-10T09:00:00")
    assert confirmed["duration_minutes"] == 60
    assert confirmed["high_risk_answers_approved_count"] == 3

    # The spokesperson-load ledger picks up exactly this booking's minutes.
    assert read_member(spox_id)["scheduled_interview_minutes"] == 60
    incident = read_incident(incident_id)
    assert incident["confirmed_interview_count"] == 1
    assert_posture(incident, "OPEN")


# ---------------------------------------------------------------------------
# The statutory override on notice sequencing (PRD §3.6)
# ---------------------------------------------------------------------------


def test_regulator_statutory_override_is_reserved_to_counsel(api):
    """PRD §3.6: "The statutory override applies only when all four of the
    following hold at once: the request sets `priority_override` to true, the
    notice's `audience` is `REGULATOR`, the acting role is `LegalCounsel` — the
    communications lead cannot invoke it even though it may otherwise release
    notices — and the current instant has reached or passed the incident's
    `activated_at` plus two hours."

    Design: Corner/validations/corner_validation_regulator_statutory_override_permits_out_of_sequence_release
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="REGULATORY_PROBE"
    )
    incident_id = scenario["incident"]["id"]
    assert scenario["incident"]["activated_at"].startswith("2026-08-10T09:00:00")

    setup_published_statement(scenario)
    employee = queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1000)
    customer = queue_notice(scenario, audience="CUSTOMER", estimated_reach=800)
    regulator = queue_notice(scenario, audience="REGULATOR", estimated_reach=2000)
    assert regulator["sequence_rank"] == 3

    # Exactly activated_at plus two hours.
    set_clock("2026-08-10T11:00:00Z")

    before = read_notice(regulator["id"])
    refused = api.release_stakeholder_notice(
        regulator["id"],
        scenario["headers"]["comms"],
        release_notice_payload(priority_override=True),
    )
    validate_error(refused, "ERR_NOTICE_SEQUENCE_VIOLATION")
    after = read_notice(regulator["id"])
    assert_no_write(before, after, "notice")
    assert after["state"] == "QUEUED"
    assert after["priority_override_used"] is False

    granted = api.release_stakeholder_notice(
        regulator["id"],
        scenario["headers"]["counsel"],
        release_notice_payload(priority_override=True),
    )
    released = validate_success(granted, 200)

    assert released["state"] == "RELEASED"
    assert released["priority_override_used"] is True
    # REGULATOR weight 1.50 * 2000 / 1000 = 3.00.
    assert_two_decimals(released["reach_contribution"], 3.00, "reach_contribution")

    # The lower-ranked notices are still unsettled, which is the whole point.
    assert read_notice(employee["id"])["state"] == "QUEUED"
    assert read_notice(customer["id"])["state"] == "QUEUED"

    incident = read_incident(incident_id)
    assert_two_decimals(
        incident["stakeholder_reach_index"], 3.00, "stakeholder_reach_index"
    )
    assert incident["released_notice_count"] == 1


# ---------------------------------------------------------------------------
# Privilege clearance outranks the seat rule (PRD §3.4)
# ---------------------------------------------------------------------------


def test_privilege_assertion_needs_cleared_counsel_not_just_the_seat(api):
    """PRD §3.4: "the acting `TeamMember` must have `privilege_cleared` true, or
    the request is refused with `ERR_PRIVILEGE_NOT_CLEARED` (HTTP 403); and that
    same member must hold a seat on this incident with `team_role`
    `LEGAL_COUNSEL` in state `ACKNOWLEDGED`, or the request is refused with
    `ERR_ASSIGNMENT_NOT_ACKNOWLEDGED` (HTTP 409)."

    Design: Corner/validations/corner_validation_privilege_assertion_requires_cleared_counsel
    """
    set_clock("2026-08-10T09:00:00Z")
    roster = seed_roster(counsel={"privilege_cleared": False})
    scenario = setup_activated_incident(
        tier="SEV2", roster=roster, scenario_code="PLANT_INCIDENT"
    )
    incident_id = scenario["incident"]["id"]

    # The seat itself is in order: counsel holds LEGAL_COUNSEL, ACKNOWLEDGED.
    seat = scenario["assignments"]["LEGAL_COUNSEL"]
    assert seat["team_role"] == "LEGAL_COUNSEL"
    assert seat["state"] == "ACKNOWLEDGED"
    assert read_member(scenario["ids"]["counsel"])["privilege_cleared"] is False

    before = read_incident(incident_id)
    response = api.assert_privilege(
        incident_id,
        assert_privilege_payload(
            privilege_basis="Anticipated litigation over the contractor injury."
        ),
        scenario["headers"]["counsel"],
    )
    validate_error(response, "ERR_PRIVILEGE_NOT_CLEARED")

    after = read_incident(incident_id)
    assert_no_write(before, after, "incident")
    assert after["privilege_state"] == "NON_PRIVILEGED"
    assert after["legal_hold_active"] is False
    assert after["privilege_basis"] is None
    assert_posture(after, "OPEN")


# ---------------------------------------------------------------------------
# A legal hold freezes drafting ahead of every other child gate (PRD §2.6)
# ---------------------------------------------------------------------------


def test_frozen_posture_blocks_statement_creation(api):
    """PRD §2.6: "A `FROZEN` posture blocks every child mutation on that
    incident, with exactly three exemptions: waiving privilege, running the
    service-level checkpoint, and scoring the post-crisis review. The rejection
    carries `ERR_COMMS_POSTURE_FROZEN` (HTTP 409)."

    Design: Corner/validations/corner_validation_frozen_posture_blocks_statement_creation
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="REGULATORY_PROBE"
    )
    incident_id = scenario["incident"]["id"]

    held = assert_privilege(
        scenario, privilege_basis="Counsel is directing the internal review."
    )
    assert held["legal_hold_active"] is True
    assert_posture(held, "FROZEN")

    # The incident is ACTIVATED and the version travelling with the draft is
    # freshly read, so nothing but the posture can refuse this create.
    before = read_incident(incident_id)
    response = api.create_statement(
        statement_payload(
            incident_id,
            before["version"],
            statement_type="HOLDING",
            body="A draft that must not be accepted under the hold.",
        ),
        scenario["headers"]["comms"],
    )
    validate_error(response, "ERR_COMMS_POSTURE_FROZEN")

    after = read_incident(incident_id)
    assert_no_write(before, after, "incident")
    assert after["privilege_state"] == "PRIVILEGED_ASSERTED"
    assert after["legal_hold_active"] is True
    assert after["response_state"] == "ACTIVATED"
    assert_posture(after, "FROZEN")

    rows, meta = validate_paginated(
        api.list_statements(scenario["headers"]["comms"], {"incident_id": incident_id})
    )
    assert_pagination_meta(meta, total_count=0)
    assert rows == []


# ---------------------------------------------------------------------------
# Channel correction capacity of two admits an overlapping pair (PRD §3.8)
# ---------------------------------------------------------------------------


def test_capacity_of_two_admits_two_overlapping_correction_windows(api):
    """PRD §3.8: "The server counts the claims on the same channel already in
    state `CORRECTION_ISSUED` whose window overlaps the requested one — overlap
    meaning the existing window's start is earlier than the requested end and
    the existing window's end is later than the requested start — and that count
    must be strictly less than the channel's `max_concurrent_corrections`."

    Design: Corner/validations/corner_validation_aggregate_capacity_two_admits_overlapping_windows
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="PLANT_INCIDENT"
    )
    incident_id = scenario["incident"]["id"]

    channel = register_channel(
        name="ShortVideo App",
        channel_type="SOCIAL",
        platform_escalation_contact="trust@shortvideo.example",
        max_concurrent_corrections=2,
    )
    verify_channel_path(channel["id"], verified_contact_reference="TS-CASE-9002")
    assert channel["max_concurrent_corrections"] == 2

    correction = add_published_statement(scenario, statement_type="CORRECTION")
    assert correction["statement_type"] == "CORRECTION"
    assert correction["state"] == "PUBLISHED"

    claim_a = log_claim(
        scenario,
        virality_score=20.00,
        channel_id=channel["id"],
        claim_text="The depot burned down last night.",
    )
    triage_claim(scenario, claim_a["id"])
    claim_b = log_claim(
        scenario,
        virality_score=20.00,
        channel_id=channel["id"],
        claim_text="Staff were evacuated by helicopter.",
    )
    triage_claim(scenario, claim_b["id"])

    first = api.issue_correction(
        claim_a["id"],
        issue_correction_payload(
            correction["id"],
            "2026-08-10T11:00:00Z",
            "2026-08-10T11:30:00Z",
            channel_version(channel["id"]),
        ),
        scenario["headers"]["comms"],
    )
    issued_a = validate_success(first, 200)
    assert issued_a["state"] == "CORRECTION_ISSUED"
    assert issued_a["correction_window_minutes"] == 30

    # 11:15-11:45 genuinely overlaps 11:00-11:30, so it consumes the second slot
    # rather than being refused.
    second = api.issue_correction(
        claim_b["id"],
        issue_correction_payload(
            correction["id"],
            "2026-08-10T11:15:00Z",
            "2026-08-10T11:45:00Z",
            channel_version(channel["id"]),
        ),
        scenario["headers"]["comms"],
    )
    issued_b = validate_success(second, 200)
    assert issued_b["state"] == "CORRECTION_ISSUED"
    assert issued_b["correction_window_minutes"] == 30
    assert issued_b["correction_statement_id"] == correction["id"]

    # The airtime ledger sums both windows.
    assert read_channel(channel["id"])["reserved_correction_minutes"] == 60
    assert read_incident(incident_id)["open_claim_count"] == 2


# ---------------------------------------------------------------------------
# The embargo comparison is inclusive at the embargo instant (PRD §3.6)
# ---------------------------------------------------------------------------


def test_embargo_equality_permits_release_one_minute_early_does_not(api):
    """PRD §3.6: "Either `embargo_until` is null or the current instant has
    reached or passed it, otherwise `ERR_EMBARGO_NOT_REACHED` (HTTP 409)."

    Design: Corner/validations/corner_validation_embargo_equality_permits_release
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:59:00Z", scenario_code="PRODUCT_RECALL"
    )
    incident_id = scenario["incident"]["id"]
    setup_published_statement(scenario)

    notice = queue_notice(
        scenario,
        audience="EMPLOYEE",
        estimated_reach=1000,
        embargo_until="2026-08-10T10:00:00Z",
    )
    # Rank 1 has no lower-ranked notice to wait for, so only the embargo can bite.
    assert notice["sequence_rank"] == 1

    before = read_notice(notice["id"])
    early = api.release_stakeholder_notice(notice["id"], scenario["headers"]["comms"])
    validate_error(early, "ERR_EMBARGO_NOT_REACHED")
    after = read_notice(notice["id"])
    assert_no_write(before, after, "notice")
    assert after["state"] == "QUEUED"
    assert after["released_at"] is None

    set_clock("2026-08-10T10:00:00Z")
    on_time = api.release_stakeholder_notice(notice["id"], scenario["headers"]["comms"])
    released = validate_success(on_time, 200)

    assert released["state"] == "RELEASED"
    assert released["released_at"].startswith("2026-08-10T10:00:00")
    # EMPLOYEE weight 1.00 * 1000 / 1000 = 1.00.
    assert_two_decimals(released["reach_contribution"], 1.00, "reach_contribution")
    assert_two_decimals(
        read_incident(incident_id)["stakeholder_reach_index"],
        1.00,
        "stakeholder_reach_index",
    )


# ---------------------------------------------------------------------------
# Seat uniqueness spans ASSIGNED as well as ACKNOWLEDGED (PRD §3.3)
# ---------------------------------------------------------------------------


def test_second_seat_on_the_same_team_role_is_refused(api):
    """PRD §3.3: "Each seat is unique per incident: if another seat on the same
    incident already holds the same `team_role` in state `ASSIGNED` or
    `ACKNOWLEDGED`, the request is refused with `ERR_DUPLICATE_ASSIGNMENT_ROLE`
    (HTTP 409)."

    Design: Corner/validations/corner_validation_duplicate_team_role_second_seat_rejected
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-10T09:00:00Z", scenario_code="PLANT_INCIDENT"
    )
    incident_id = scenario["incident"]["id"]
    lead_id = scenario["ids"]["lead"]
    other_id = scenario["ids"]["exec"]

    first = validate_success(
        api.create_team_assignment(
            team_assignment_payload(
                incident_id, lead_id, "INCIDENT_LEAD", decision_authority="FULL"
            ),
            scenario["headers"]["lead"],
        ),
        201,
    )
    # The incumbent seat has not been acknowledged yet, and that is enough.
    assert first["state"] == "ASSIGNED"

    response = api.create_team_assignment(
        team_assignment_payload(
            incident_id, other_id, "INCIDENT_LEAD", decision_authority="LIMITED"
        ),
        scenario["headers"]["lead"],
    )
    validate_error(response, "ERR_DUPLICATE_ASSIGNMENT_ROLE")

    assert read_assignment(first["id"])["state"] == "ASSIGNED"
    rows, meta = validate_paginated(
        api.list_team_assignments(
            scenario["headers"]["lead"],
            {"incident_id": incident_id, "team_role": "INCIDENT_LEAD"},
        )
    )
    assert_pagination_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [first["id"]]
    assert read_member(other_id)["active_assignment_count"] == 0


# ---------------------------------------------------------------------------
# Open notices outrank open claims on resolution (PRD §2.9, §3.9)
# ---------------------------------------------------------------------------


def test_open_notices_are_reported_before_open_claims_on_resolve(api):
    """PRD §3.9: "the incident must have no stakeholder notice in `QUEUED` or
    `BLOCKED`, or the request is refused with `ERR_OPEN_NOTICES_BLOCK_RESOLUTION`
    (HTTP 409); and its `open_claim_count` must be exactly 0, meaning every
    misinformation claim has reached `CLOSED`, or the refusal is
    `ERR_OPEN_CLAIMS_BLOCK_RESOLUTION` (HTTP 409)."

    Design: Corner/validations/corner_validation_open_notices_outrank_open_claims_on_resolve
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="PRODUCT_RECALL"
    )
    incident_id = scenario["incident"]["id"]

    statement = draft_statement(scenario, statement_type="HOLDING")
    notice = queue_notice(scenario, audience="EMPLOYEE", estimated_reach=500)
    claim = log_claim(
        scenario,
        virality_score=30.00,
        claim_text="Every product line is contaminated.",
    )
    assert statement["state"] == "DRAFT"
    assert notice["state"] == "QUEUED"
    assert claim["state"] == "DETECTED"

    # Both blockers are violated at once; the lower-numbered rule answers.
    before = read_incident(incident_id)
    first = api.resolve_incident(
        incident_id,
        scenario["headers"]["lead"],
        resolve_incident_payload(reputation_index_after=48.00),
    )
    validate_error(first, "ERR_OPEN_NOTICES_BLOCK_RESOLUTION")
    assert_no_write(before, read_incident(incident_id), "incident")

    cancel_notice(
        scenario, notice["id"], cancel_reason="Superseded by the recall page."
    )
    assert read_notice(notice["id"])["state"] == "CANCELLED"

    second = api.resolve_incident(
        incident_id,
        scenario["headers"]["lead"],
        resolve_incident_payload(reputation_index_after=48.00),
    )
    validate_error(second, "ERR_OPEN_CLAIMS_BLOCK_RESOLUTION")

    assert read_claim(claim["id"])["state"] == "DETECTED"
    incident = read_incident(incident_id)
    assert incident["response_state"] == "ACTIVATED"
    assert incident["resolved_at"] is None
    assert incident["open_claim_count"] == 1

    rows, meta = validate_paginated(
        api.list_post_crisis_reviews(
            make_program_admin_headers(), {"incident_id": incident_id}
        )
    )
    assert_pagination_meta(meta, total_count=0)
    assert rows == []


# ---------------------------------------------------------------------------
# Media training must outlive the confirmation instant (PRD §3.7)
# ---------------------------------------------------------------------------


def test_training_expiring_at_the_confirmation_instant_blocks_confirmation(api):
    """PRD §3.7: "The spokesperson's `media_training_status` must be `CURRENT`
    **and** their `media_training_expires_at` must be strictly after the current
    instant, so training that lapses exactly at the confirmation instant does not
    count; failure gives `ERR_TRAINING_NOT_CURRENT` (HTTP 422)."

    Design: Corner/validations/corner_validation_training_expiry_equality_blocks_confirmation
    """
    set_clock("2026-08-10T09:00:00Z")
    roster = seed_roster(
        spox={
            "media_training_status": "CURRENT",
            "media_training_expires_at": "2026-08-10T09:00:00.000Z",
        }
    )
    scenario = setup_activated_incident(
        tier="SEV2", roster=roster, scenario_code="PLANT_INCIDENT"
    )
    incident_id = scenario["incident"]["id"]
    spox_id = scenario["ids"]["spox"]

    spox = read_member(spox_id)
    assert spox["media_training_status"] == "CURRENT"
    assert spox["media_training_expires_at"].startswith("2026-08-10T09:00:00")

    # The pack is complete, so only the training clock can refuse this.
    interview = book_interview(
        scenario,
        "2026-08-12T14:00:00Z",
        "2026-08-12T15:00:00Z",
        anticipated_question_count=8,
    )
    before = read_interview(interview["id"])
    response = api.confirm_media_interview(
        interview["id"],
        scenario["headers"]["comms"],
        confirm_interview_payload(high_risk_answers_approved_count=3),
    )
    validate_error(response, "ERR_TRAINING_NOT_CURRENT")

    after = read_interview(interview["id"])
    assert_no_write(before, after, "interview")
    assert after["state"] == "SCHEDULED"
    assert after["confirmed_at"] is None
    assert read_member(spox_id)["scheduled_interview_minutes"] == 0
    assert read_incident(incident_id)["confirmed_interview_count"] == 0


# ---------------------------------------------------------------------------
# The platform-escalation virality floor is inclusive at 60.00 (PRD §3.8)
# ---------------------------------------------------------------------------


def test_virality_floor_refuses_fifty_nine_and_admits_sixty(api):
    """PRD §3.8: "the claim's `virality_score` must be at least 60.00, because
    trust-and-safety escalation is reserved for claims with real spread, and
    failure gives `ERR_VIRALITY_THRESHOLD_NOT_MET` (HTTP 422)."

    Design: Corner/validations/corner_validation_virality_floor_rejects_fifty_nine_admits_sixty
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="DATA_BREACH"
    )
    incident_id = scenario["incident"]["id"]

    channel = register_channel(
        name="ShortVideo App",
        channel_type="SOCIAL",
        platform_escalation_contact="trust@shortvideo.example",
    )
    verified = verify_channel_path(
        channel["id"], verified_contact_reference="TS-CASE-3310"
    )
    assert verified["escalation_path_state"] == "VERIFIED"

    low = log_claim(
        scenario,
        virality_score=59.00,
        channel_id=channel["id"],
        claim_text="Card numbers are being sold in bulk.",
    )
    triage_claim(scenario, low["id"])
    high = log_claim(
        scenario,
        virality_score=60.00,
        channel_id=channel["id"],
        claim_text="Passwords were published in plain text.",
    )
    triage_claim(scenario, high["id"])

    before = read_claim(low["id"])
    refused = api.escalate_platform(low["id"], scenario["headers"]["listener"])
    validate_error(refused, "ERR_VIRALITY_THRESHOLD_NOT_MET")
    after = read_claim(low["id"])
    assert_no_write(before, after, "claim")
    assert after["state"] == "TRIAGED"

    granted = api.escalate_platform(high["id"], scenario["headers"]["listener"])
    escalated = validate_success(granted, 200)
    assert escalated["state"] == "PLATFORM_ESCALATED"

    channel_after = read_channel(channel["id"])
    assert channel_after["open_escalation_count"] == 1
    assert channel_after["reserved_correction_minutes"] == 0
    assert read_incident(incident_id)["open_claim_count"] == 2


# ---------------------------------------------------------------------------
# Actor resolution for the entity-backed roles (PRD §2.1, §2.9)
# ---------------------------------------------------------------------------


def test_unknown_acting_member_id_is_a_not_found(api):
    """PRD §2.1: "On any endpoint whose authorised roles include one of those six
    entity-backed roles, an `X-User-ID` that does not resolve to an existing
    `TeamMember` is rejected with `ERR_TEAM_MEMBER_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/corner_validation_unknown_actor_header_not_found
    """
    set_clock("2026-08-10T09:00:00Z")
    known = register_member(full_name="Dana Ruiz", org_title="VP Operations")

    response = api.create_incident(
        incident_payload(
            title="Incident opened by a ghost", scenario_code="PRODUCT_RECALL"
        ),
        make_incident_lead_headers(NON_EXISTENT_UUID),
    )
    validate_error(response, "ERR_TEAM_MEMBER_NOT_FOUND")

    rows, meta = validate_paginated(api.list_incidents(make_program_admin_headers()))
    assert_pagination_meta(meta, total_count=0)
    assert rows == []
    assert read_member(known["id"])["active_assignment_count"] == 0


# ---------------------------------------------------------------------------
# Interval sanity belongs to the schema gate (PRD §3.7)
# ---------------------------------------------------------------------------


def test_interview_end_equal_to_start_is_a_schema_rejection(api):
    """PRD §3.7: "Those two instants describe a closed interval whose end must be
    strictly after its start; an end at or before the start is a malformed
    request and is refused with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/corner_validation_interview_interval_end_not_after_start_rejected
    """
    scenario = setup_activated_incident(
        tier="SEV2", clock="2026-08-10T09:00:00Z", scenario_code="PLANT_INCIDENT"
    )
    incident_id = scenario["incident"]["id"]
    spox_id = scenario["ids"]["spox"]

    response = api.create_media_interview(
        media_interview_payload(
            incident_id,
            spox_id,
            scenario["channel"]["id"],
            "2026-08-12T14:00:00Z",
            "2026-08-12T14:00:00Z",
            outlet_name="Evening Bulletin",
            anticipated_question_count=8,
        ),
        scenario["headers"]["comms"],
    )
    validate_error(response, "ERR_INVALID_REQUEST")

    rows, meta = validate_paginated(
        api.list_media_interviews(
            scenario["headers"]["comms"], {"incident_id": incident_id}
        )
    )
    assert_pagination_meta(meta, total_count=0)
    assert rows == []
    assert read_member(spox_id)["scheduled_interview_minutes"] == 0
