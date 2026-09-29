"""Scarce resources booked over time: the spokesperson calendar padded by a
thirty-minute buffer and the channel's half-open correction airtime
(PRD §3.7, §3.8)."""

from test_helpers import (
    ApiErrorId,
    assert_field,
    assert_state,
    book_interview,
    filter_by,
    issue_correction,
    list_rows,
    log_claim,
    read_channel,
    read_claim,
    read_interview,
    read_member,
    refresh,
    setup_activated_incident,
    setup_published_statement,
    triage_claim,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# TeamMember: a closed booking interval padded by thirty minutes each side
# ---------------------------------------------------------------------------


def _spokesperson_booked_from_two_to_three():
    """A SEV2 incident whose trained spokesperson already holds one SCHEDULED
    interview running 2026-08-12T14:00:00Z to 15:00:00Z."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PRODUCT_RECALL",
        title="Recall logistics questions",
    )
    scenario["first"] = book_interview(
        scenario,
        "2026-08-12T14:00:00Z",
        "2026-08-12T15:00:00Z",
        anticipated_question_count=8,
        outlet_name="Wire Afternoon",
    )
    assert_state(scenario["first"], "SCHEDULED", "first interview")
    return scenario


def _booking_payload(scenario, outlet_name, start_at, end_at):
    """A booking request for the scenario's spokesperson on the same surface."""
    return {
        "incident_id": scenario["incident"]["id"],
        "spokesperson_member_id": scenario["ids"]["spox"],
        "channel_id": scenario["channel"]["id"],
        "outlet_name": outlet_name,
        "scheduled_start_at": start_at,
        "scheduled_end_at": end_at,
        "anticipated_question_count": 8,
    }


def test_a_start_one_minute_inside_the_buffer_is_a_double_booking(api):
    """PRD §3.7: "the clash test is satisfied when the requested
    `scheduled_start_at` is earlier than the existing interview's
    `scheduled_end_at` plus thirty minutes **and** the requested
    `scheduled_end_at` plus thirty minutes is later than the existing interview's
    `scheduled_start_at`; when both halves hold, the request is refused with
    `ERR_SPOKESPERSON_DOUBLE_BOOKED` (HTTP 409)."

    A start at 15:29 is one minute short of the padded end of 15:30, so both
    halves hold and the booking never comes into existence.  PRD §3.7 also notes
    that "a merely `SCHEDULED` interview still occupies the calendar for this
    test even though it contributes nothing to `scheduled_interview_minutes`".

    Design: Difficulty/resource_temporal_overlap/overlap_spokesperson_calendar_closed_interval_with_thirty_minute_buffer
    """
    scenario = _spokesperson_booked_from_two_to_three()

    validate_error(
        api.create_media_interview(
            _booking_payload(
                scenario, "Wire Drivetime", "2026-08-12T15:29:00Z", "2026-08-12T16:29:00Z"
            ),
            scenario["headers"]["comms"],
        ),
        ApiErrorId.ERR_SPOKESPERSON_DOUBLE_BOOKED,
        409,
    )

    rows = list_rows(
        "list_media_interviews", spokesperson_member_id=scenario["ids"]["spox"]
    )
    assert filter_by(rows, outlet_name="Wire Drivetime") == [], (
        "a refused booking must leave no interview row behind"
    )
    assert len(rows) == 1, f"the calendar must still hold one booking, got {len(rows)}"
    assert_state(read_interview(scenario["first"]["id"]), "SCHEDULED", "first interview")
    assert_field(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 0,
        "spokesperson",
    )


def test_a_gap_of_exactly_the_buffer_is_permitted(api):
    """PRD §3.7: "A gap of exactly thirty minutes between two bookings is
    therefore permitted, since neither strict comparison holds at the boundary."

    A start at 15:30 sits exactly on the padded end of the 14:00-15:00 booking, so
    the second interview is accepted and the server derives `duration_minutes` as
    "the whole number of complete minutes between the two endpoints".

    Design: Difficulty/resource_temporal_overlap/overlap_spokesperson_calendar_closed_interval_with_thirty_minute_buffer
    """
    scenario = _spokesperson_booked_from_two_to_three()

    second = validate_success(
        api.create_media_interview(
            _booking_payload(
                scenario, "Wire Nightly", "2026-08-12T15:30:00Z", "2026-08-12T16:30:00Z"
            ),
            scenario["headers"]["comms"],
        ),
        201,
    )

    assert_state(second, "SCHEDULED", "second interview")
    assert_field(second, "duration_minutes", 60, "second interview")
    assert second["confirmed_at"] is None, "a new booking starts unconfirmed"
    assert_state(read_interview(scenario["first"]["id"]), "SCHEDULED", "first interview")
    assert (
        len(
            list_rows(
                "list_media_interviews", spokesperson_member_id=scenario["ids"]["spox"]
            )
        )
        == 2
    ), "both bookings must stand on the spokesperson's calendar"
    assert_field(
        read_member(scenario["ids"]["spox"]), "scheduled_interview_minutes", 0,
        "spokesperson",
    )


# ---------------------------------------------------------------------------
# MonitoredChannel: half-open correction windows against an aggregate capacity
# ---------------------------------------------------------------------------


def _three_triaged_claims_on_a_single_capacity_channel():
    """A SEV2 incident on a SOCIAL surface that tolerates one concurrent
    correction, carrying a PUBLISHED CORRECTION statement and three TRIAGED claims
    of virality 20.00 each."""
    scenario = setup_activated_incident(
        tier="SEV2",
        clock="2026-08-10T09:00:00Z",
        scenario_code="PRODUCT_RECALL",
        channel_type="SOCIAL",
        title="False refund claims spreading",
    )
    channel = read_channel(scenario["channel"]["id"])
    assert_field(channel, "max_concurrent_corrections", 1, "channel")
    assert_field(channel, "reserved_correction_minutes", 0, "channel")
    setup_published_statement(
        scenario,
        statement_type="CORRECTION",
        body="No automatic refunds are being issued; here is the actual process.",
    )
    labels = ("early", "touching", "straddle")
    texts = (
        "Refunds are automatic for everyone.",
        "The refund window closes tonight.",
        "Refunds require a lawyer.",
    )
    for label, text in zip(labels, texts):
        scenario[label] = log_claim(scenario, virality_score=20.00, claim_text=text)
        triage_claim(scenario, claim_id=scenario[label]["id"])
        scenario[label] = read_claim(scenario[label]["id"])
        assert_state(scenario[label], "TRIAGED", f"{label} claim")
    return scenario


def test_a_window_starting_exactly_when_another_ends_does_not_consume_capacity(api):
    """PRD §3.8: "Correction windows are **half-open** intervals: a window covers
    its start instant and every instant up to but not including its end. ...
    Because the arithmetic is half-open, a window that starts at exactly the
    instant another one ends does not overlap it and does not consume capacity."

    An 11:30-12:00 window therefore lands beside the existing 11:00-11:30 one even
    though the channel tolerates only a single concurrent correction, and the two
    thirty-minute reservations aggregate to sixty minutes of airtime.

    Design: Difficulty/resource_temporal_overlap/overlap_channel_correction_airtime_half_open_aggregate_capacity
    """
    scenario = _three_triaged_claims_on_a_single_capacity_channel()

    early = issue_correction(
        scenario,
        "2026-08-10T11:00:00Z",
        "2026-08-10T11:30:00Z",
        claim_id=scenario["early"]["id"],
    )
    touching = issue_correction(
        scenario,
        "2026-08-10T11:30:00Z",
        "2026-08-10T12:00:00Z",
        claim_id=scenario["touching"]["id"],
    )

    assert_state(early, "CORRECTION_ISSUED", "early claim")
    assert_field(early, "correction_window_minutes", 30, "early claim")
    assert_state(touching, "CORRECTION_ISSUED", "touching claim")
    assert_field(touching, "correction_window_minutes", 30, "touching claim")
    assert_field(
        read_channel(scenario["channel"]["id"]), "reserved_correction_minutes", 60,
        "channel",
    )


def test_a_window_straddling_both_reservations_exceeds_the_capacity(api):
    """PRD §3.8: "The server counts the claims on the same channel already in state
    `CORRECTION_ISSUED` whose window overlaps the requested one — overlap meaning
    the existing window's start is earlier than the requested end and the existing
    window's end is later than the requested start — and that count must be
    strictly less than the channel's `max_concurrent_corrections`. If it is not,
    the request is refused with `ERR_CHANNEL_CORRECTION_CAPACITY` (HTTP 409)."

    An 11:15-11:45 window overlaps both reserved windows, so the count of two is
    not strictly less than the capacity of one, the third claim stays `TRIAGED`,
    and the airtime ledger is untouched at sixty minutes.

    Design: Difficulty/resource_temporal_overlap/overlap_channel_correction_airtime_half_open_aggregate_capacity
    """
    scenario = _three_triaged_claims_on_a_single_capacity_channel()
    issue_correction(
        scenario,
        "2026-08-10T11:00:00Z",
        "2026-08-10T11:30:00Z",
        claim_id=scenario["early"]["id"],
    )
    issue_correction(
        scenario,
        "2026-08-10T11:30:00Z",
        "2026-08-10T12:00:00Z",
        claim_id=scenario["touching"]["id"],
    )
    channel_before = read_channel(scenario["channel"]["id"])

    validate_error(
        api.issue_correction(
            scenario["straddle"]["id"],
            {
                "correction_statement_id": scenario["statement"]["id"],
                "correction_window_start": "2026-08-10T11:15:00Z",
                "correction_window_end": "2026-08-10T11:45:00Z",
                "expected_channel_version": channel_before["version"],
            },
            scenario["headers"]["comms"],
        ),
        ApiErrorId.ERR_CHANNEL_CORRECTION_CAPACITY,
        409,
    )

    straddle = read_claim(scenario["straddle"]["id"])
    assert_state(straddle, "TRIAGED", "straddling claim")
    assert_field(straddle, "correction_statement_id", None, "straddling claim")
    assert_field(straddle, "correction_window_minutes", 0, "straddling claim")
    channel_after = read_channel(scenario["channel"]["id"])
    assert_field(channel_after, "reserved_correction_minutes", 60, "channel")
    assert channel_after["version"] == channel_before["version"], (
        "a refused correction must not advance the channel version, got "
        f"{channel_before['version']} then {channel_after['version']}"
    )
    assert_field(refresh(scenario), "open_claim_count", 3, "incident")
