"""Optimistic concurrency on shared parents, and the immediate visibility of
every recomputed value.

The version counter is exercised as a write counter: reads never move it, each
mutation moves it by exactly one, and a stale token is refused before anything is
written.
"""

from test_helpers import (
    assert_field,
    assert_ledger,
    assert_no_write,
    assert_state,
    assert_timestamp_format,
    assert_two_decimals,
    assert_version,
    book_interview,
    channel_version,
    confirm_interview_payload,
    escalate_signal,
    incident_version,
    issue_correction_payload,
    link_signal,
    log_claim,
    queue_notice,
    read_channel,
    read_claim,
    read_incident,
    read_interview,
    read_member,
    read_notice,
    read_statement,
    record_signal,
    register_channel,
    seat_member,
    setup_activated_incident,
    setup_monitoring_incident,
    setup_published_statement,
    statement_payload,
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
# Optimistic concurrency on the incident (PRD §2.8, §3.5)
# ---------------------------------------------------------------------------


def test_stale_incident_version_rejects_the_superseding_draft(api):
    """PRD §2.8: "Creating a statement requires the request to carry
    `expected_incident_version` as a non-optional field, holding the `version` of
    the target `Incident` that the client last observed. If that value does not
    equal the incident's current `version`, the create is rejected with
    `ERR_STALE_INCIDENT_VERSION` (HTTP 412). This guard matters precisely because
    no state precondition covers the case: a new `HOLDING` draft legitimately
    supersedes an earlier one, so a second create is structurally permitted."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_incident_version_rejects_the_superseding_draft
    """
    scenario = setup_activated_incident(clock="2026-08-10T09:00:00Z", tier="SEV2")
    incident_id = scenario["incident"]["id"]
    comms = scenario["headers"]["comms"]
    # The version the client caches from the activation response.
    cached = scenario["incident"]["version"]

    first = validate_success(
        api.create_statement(
            statement_payload(
                incident_id,
                cached,
                statement_type="HOLDING",
                body="First holding statement.",
            ),
            comms,
        ),
        201,
    )
    # Drafting increments the incident's version by 1, which is exactly what
    # invalidates the cached token (PRD §3.5).
    assert incident_version(incident_id) == cached + 1, (
        "creating a statement must advance the incident's version by exactly 1"
    )

    stale = api.create_statement(
        statement_payload(
            incident_id,
            cached,
            statement_type="HOLDING",
            body="Second holding statement from a stale client.",
            supersedes_statement_id=first["id"],
        ),
        comms,
    )
    validate_error(stale, "ERR_STALE_INCIDENT_VERSION")

    # The refused create wrote nothing at all.
    rows, meta = validate_paginated(
        api.list_statements(comms, {"incident_id": incident_id})
    )
    assert meta["total_count"] == 1, (
        f"the refused draft must not exist; got {meta['total_count']} statements"
    )
    assert len(rows) == 1, f"expected exactly one statement row, got {len(rows)}"
    refreshed = read_incident(incident_id)
    assert_version(refreshed, cached + 1, "incident")

    # Re-reading the parent yields the token the writer needed.
    re_read = incident_version(incident_id)
    assert re_read == cached + 1, "the re-read version is the post-first-draft value"

    second = validate_success(
        api.create_statement(
            statement_payload(
                incident_id,
                re_read,
                statement_type="HOLDING",
                body="Second holding statement, retried after a re-read.",
                supersedes_statement_id=first["id"],
            ),
            comms,
        ),
        201,
    )
    assert_field(second, "supersedes_statement_id", first["id"], "statement")
    assert_version(read_incident(incident_id), re_read + 1, "incident")
    assert_state(read_statement(first["id"]), "DRAFT", "first statement")
    assert_state(second, "DRAFT", "second statement")


# ---------------------------------------------------------------------------
# Optimistic concurrency on the channel (PRD §2.8, §3.8)
# ---------------------------------------------------------------------------


def test_stale_channel_version_rejects_the_correction_window(api):
    """PRD §2.8: "Issuing a correction against a misinformation claim requires
    the request to carry `expected_channel_version` as a non-optional field,
    holding the `version` of the referenced `MonitoredChannel` that the client
    last observed. If that value does not equal the channel's current `version`,
    the request is rejected with `ERR_STALE_CHANNEL_VERSION` (HTTP 412)."
    PRD §3.1: verifying the escalation path "moves `escalation_path_state` from
    `UNVERIFIED` to `VERIFIED`, and increments the channel's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_channel_version_rejects_the_correction_window
    """
    scenario = setup_published_statement(
        clock="2026-08-10T09:00:00Z", tier="SEV2", statement_type="CORRECTION"
    )
    correction_statement = scenario["statement"]
    social = register_channel(
        name="ShortVideo App",
        channel_type="SOCIAL",
        platform_escalation_contact="trust@shortvideo.example",
    )

    log_claim(scenario, virality_score=55.00, channel_id=social["id"])
    claim = triage_claim(scenario)
    assert_state(claim, "TRIAGED", "claim")

    # The version the client caches before the administrator touches the channel.
    cached = channel_version(social["id"])
    verify_channel_path(social["id"], verified_contact_reference="TS-CASE-9001")

    window = {
        "correction_window_start": "2026-08-10T11:00:00Z",
        "correction_window_end": "2026-08-10T11:30:00Z",
    }
    stale = api.issue_correction(
        claim["id"],
        issue_correction_payload(
            correction_statement["id"],
            window["correction_window_start"],
            window["correction_window_end"],
            cached,
        ),
        scenario["headers"]["comms"],
    )
    validate_error(stale, "ERR_STALE_CHANNEL_VERSION")

    after_refusal = read_claim(claim["id"])
    assert_state(after_refusal, "TRIAGED", "claim")
    assert_field(after_refusal, "correction_window_minutes", 0, "claim")
    assert_no_write(claim, after_refusal, "claim")
    # No airtime is reserved by a refused call.
    assert_ledger(read_channel(social["id"]), "reserved_correction_minutes", 0)

    re_read = channel_version(social["id"])
    assert re_read == cached + 1, (
        "verifying the escalation path advances the channel's version by 1"
    )

    issued = validate_success(
        api.issue_correction(
            claim["id"],
            issue_correction_payload(
                correction_statement["id"],
                window["correction_window_start"],
                window["correction_window_end"],
                re_read,
            ),
            scenario["headers"]["comms"],
        )
    )
    assert_state(issued, "CORRECTION_ISSUED", "claim")
    # 11:00 to 11:30 is 30 complete minutes.
    assert_field(issued, "correction_window_minutes", 30, "claim")

    channel = read_channel(social["id"])
    assert_ledger(channel, "reserved_correction_minutes", 30)
    assert_version(channel, re_read + 1, "channel")


# ---------------------------------------------------------------------------
# The version counter is a write counter (PRD §2.4)
# ---------------------------------------------------------------------------


def test_incident_version_advances_only_on_writes(api):
    """PRD §2.4: "`version` is an integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of that resource." PRD §3.3, on the
    operator checkpoint: "Finally it recomputes `comms_posture` and increments the
    incident's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_version_advances_only_on_writes
    """
    scenario = setup_monitoring_incident(
        clock="2026-08-10T09:00:00Z", scenario_code="DATA_BREACH"
    )
    incident_id = scenario["incident"]["id"]
    listener = scenario["headers"]["listener"]

    signal = record_signal(scenario["channel"]["id"], listener, reach_score=75)
    link_signal(signal["id"], incident_id, listener)
    escalate_signal(signal["id"], listener)
    seat_member(
        incident_id,
        scenario["ids"]["lead"],
        "INCIDENT_LEAD",
        scenario["headers"]["lead"],
        member_headers=scenario["headers"]["lead"],
    )

    start = read_incident(incident_id)["version"]

    # Three reads in a row: one single read, one more single read, one listing.
    assert read_incident(incident_id)["version"] == start, (
        "reading an incident must not advance its version"
    )
    assert read_incident(incident_id, scenario["headers"]["comms"])["version"] == start
    rows, _meta = validate_paginated(api.list_incidents(scenario["headers"]["admin"]))
    listed = [row for row in rows if row["id"] == incident_id]
    assert len(listed) == 1, "the incident must appear exactly once in the listing"
    assert listed[0]["version"] == start, "listing must not advance the version"

    activated = validate_success(
        api.activate_incident(incident_id, scenario["headers"]["lead"])
    )
    assert_version(activated, start + 1, "incident")

    validate_success(
        api.create_statement(
            statement_payload(
                incident_id,
                activated["version"],
                statement_type="HOLDING",
                body="Service is being restored.",
            ),
            scenario["headers"]["comms"],
        ),
        201,
    )

    swept = validate_success(api.sla_sweep(incident_id, scenario["headers"]["admin"]))

    # Three mutations only: activate, statement create, checkpoint sweep.
    assert swept["version"] == start + 3, (
        f"expected {start + 3} after three writes and four reads, "
        f"got {swept['version']}"
    )
    assert read_incident(incident_id)["version"] == start + 3, (
        "the closing read must not advance the counter either"
    )
    assert_field(swept, "response_state", "ACTIVATED", "incident")
    # activated_at 09:00 plus the SEV2 window of 60 minutes is 10:00, and the
    # clock still reads 09:00, so the checkpoint latches nothing.
    assert_field(swept, "sla_breached", False, "incident")


# ---------------------------------------------------------------------------
# Immediate visibility of recomputed values (PRD §2.7, §3.6, §3.7)
# ---------------------------------------------------------------------------


def test_release_response_already_carries_the_recomputed_reach_index(api):
    """PRD §3.6: "a released notice's `reach_contribution` is its audience weight
    multiplied by its `estimated_reach`, divided by one thousand, rounded half up
    to two decimals ... The incident's `stakeholder_reach_index` is then rebuilt
    from scratch on every release ... Release also recomputes
    `released_notice_count` and increments the incident's `version` by 1."

    Design: Corner/consistency_model/corner_consistency_release_response_already_carries_the_recomputed_index
    """
    scenario = setup_published_statement(clock="2026-08-10T09:00:00Z", tier="SEV2")
    notice = queue_notice(scenario, audience="EMPLOYEE", estimated_reach=1000)
    assert_two_decimals(notice["reach_contribution"], 0.00, "reach_contribution")

    released = validate_success(
        api.release_stakeholder_notice(notice["id"], scenario["headers"]["comms"])
    )

    # The release response itself is authoritative: no follow-up call is needed.
    assert_state(released, "RELEASED", "notice")
    _assert_instant(released["released_at"], "2026-08-10T09:00:00", "released_at")
    # EMPLOYEE weight 1.00 * 1000 / 1000 = 1.00
    assert_two_decimals(released["reach_contribution"], 1.00, "reach_contribution")

    incident = read_incident(scenario["incident"]["id"])
    assert_field(incident, "released_notice_count", 1, "incident")
    assert_field(incident, "blocked_notice_count", 0, "incident")
    assert_two_decimals(
        incident["stakeholder_reach_index"], 1.00, "stakeholder_reach_index"
    )

    # A second read of the same rows reports the identical values, so nothing was
    # left to settle.
    again = read_notice(notice["id"])
    assert_two_decimals(again["reach_contribution"], 1.00, "reach_contribution")
    assert_state(again, "RELEASED", "notice")
    assert_no_write(released, again, "notice")
    assert_two_decimals(
        read_incident(scenario["incident"]["id"])["stakeholder_reach_index"],
        1.00,
        "stakeholder_reach_index",
    )

    statement = read_statement(scenario["statement"]["id"])
    assert_state(statement, "PUBLISHED", "statement")
    _assert_instant(
        incident["holding_statement_published_at"],
        "2026-08-10T09:00:00",
        "holding_statement_published_at",
    )
    assert_field(incident, "sla_breached", False, "incident")
    assert_field(incident, "comms_posture", "OPEN", "incident")


def test_confirmed_interview_minutes_are_visible_to_the_next_read(api):
    """PRD §3.7: "On success `confirmed_at` is stamped, the spokesperson's
    `scheduled_interview_minutes` increases by exactly this interview's
    `duration_minutes`, the incident's `confirmed_interview_count` is recomputed,
    and the incident's `version` is incremented by 1." PRD §2.7: "A member's
    `scheduled_interview_minutes` is the sum of `duration_minutes` over
    interviews where that member is the spokesperson and the interview is in state
    `CONFIRMED`."

    Design: Corner/consistency_model/corner_consistency_ledger_write_is_visible_to_the_next_read
    """
    scenario = setup_activated_incident(
        clock="2026-08-10T09:00:00Z", tier="SEV2", scenario_code="PLANT_INCIDENT"
    )
    spokesperson_id = scenario["ids"]["spox"]
    assert_ledger(read_member(spokesperson_id), "scheduled_interview_minutes", 0)

    interview = book_interview(
        scenario,
        "2026-08-12T10:00:00Z",
        "2026-08-12T10:45:00Z",
        anticipated_question_count=8,
        outlet_name="Morning Wire",
    )
    # 10:00 to 10:45 is 45 complete minutes.
    assert_field(interview, "duration_minutes", 45, "interview")
    # A merely SCHEDULED booking contributes nothing to the ledger.
    assert_ledger(read_member(spokesperson_id), "scheduled_interview_minutes", 0)

    confirmed = validate_success(
        api.confirm_media_interview(
            interview["id"],
            scenario["headers"]["comms"],
            confirm_interview_payload(high_risk_answers_approved_count=3),
        )
    )
    assert_state(confirmed, "CONFIRMED", "interview")
    assert_field(confirmed, "duration_minutes", 45, "interview")
    _assert_instant(confirmed["confirmed_at"], "2026-08-10T09:00:00", "confirmed_at")

    # The write reached the other two aggregates inside the same operation.
    member = read_member(spokesperson_id)
    assert_ledger(member, "scheduled_interview_minutes", 45)
    incident = read_incident(scenario["incident"]["id"])
    assert_field(incident, "confirmed_interview_count", 1, "incident")

    # A second identical pair of reads reports the same values: the writes were
    # complete, not queued.
    member_again = read_member(spokesperson_id)
    assert_ledger(member_again, "scheduled_interview_minutes", 45)
    assert_no_write(member, member_again, "team member")
    incident_again = read_incident(scenario["incident"]["id"])
    assert_field(incident_again, "confirmed_interview_count", 1, "incident")
    assert_no_write(incident, incident_again, "incident")
    assert_state(read_interview(interview["id"]), "CONFIRMED", "interview")
