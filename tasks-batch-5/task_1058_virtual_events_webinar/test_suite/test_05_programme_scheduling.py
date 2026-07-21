"""The programme: half-open track slots, buffered speaker calendars and the
cyclic invite / withdraw / re-invite loop on the session-speaker junction."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_session,
    assert_speaker,
    assert_session_speaker,
    make_speaker_headers,
    new_event,
    add_track,
    add_session,
    add_speaker,
    invite_speaker,
    accept_invitation,
    schedule_session,
    read_session,
    read_speaker,
    read_session_speaker,
    read_track,
    setup_session_with_accepted_speaker,
)

ORG = TEST_USERS["organizer_headers"]


# ==========================================================================
# Half-open track geometry
# ==========================================================================

def _summit_o_track_with_two_scheduled_sessions():
    """S1 10:00-11:00 and S2 11:00-12:00 both scheduled (zero-gap adjacency),
    S3 10:30-11:30 still DRAFT."""
    event = new_event(name="Summit O")
    track = add_track(event["id"])
    s1 = add_session(
        event["id"], track["id"], title="S1",
        starts_at="2026-09-25T10:00:00Z", ends_at="2026-09-25T11:00:00Z",
    )
    schedule_session(s1["id"])
    s2 = add_session(
        event["id"], track["id"], title="S2",
        starts_at="2026-09-25T11:00:00Z", ends_at="2026-09-25T12:00:00Z",
    )
    s2_scheduled = schedule_session(s2["id"])
    s3 = add_session(
        event["id"], track["id"], title="S3",
        starts_at="2026-09-25T10:30:00Z", ends_at="2026-09-25T11:30:00Z",
    )
    return event, track, s1, s2_scheduled, s3


def test_track_slot_allows_zero_gap_adjacency(api):
    """PRD 2.10: "Two sessions on the same track conflict when the new session's
    `starts_at` is strictly earlier than the other session's `ends_at` **and**
    the other session's `starts_at` is strictly earlier than the new session's
    `ends_at`. Zero-gap adjacency — a session starting at the exact instant
    another one ends — is therefore permitted."
    PRD 3.6: "A conflict is refused with `ERR_TRACK_SLOT_CONFLICT`; a success
    increments the track's `scheduled_session_count`."

    Design: Difficulty/resource_temporal_overlap/track_slot_half_open_allows_zero_gap_adjacency_rejects_overlap
    """
    event, track, s1, s2_scheduled, s3 = _summit_o_track_with_two_scheduled_sessions()

    assert_session(s2_scheduled)
    assert s2_scheduled["state"] == "SCHEDULED", (
        "A session starting exactly when the previous one ends must schedule; got "
        f"{s2_scheduled['state']}"
    )
    assert read_track(track["id"])["scheduled_session_count"] == 2, (
        "Both adjacent sessions occupy the track"
    )


def test_track_slot_rejects_a_straddling_interval(api):
    """PRD 3.6: "It moves the session `DRAFT → SCHEDULED`, requires the owning
    event to be in `DRAFT` or `PUBLISHED`, and enforces the half-open track
    geometry from Section 2.10 against every other session on the same `track_id`
    sitting in `SCHEDULED`, `LIVE` or `COMPLETED`. A conflict is refused with
    `ERR_TRACK_SLOT_CONFLICT`; a success increments the track's
    `scheduled_session_count`."

    Design: Difficulty/resource_temporal_overlap/track_slot_half_open_allows_zero_gap_adjacency_rejects_overlap
    """
    event, track, s1, s2_scheduled, s3 = _summit_o_track_with_two_scheduled_sessions()

    validate_error(
        api.schedule_session(s3["id"], ORG), ApiErrorId.ERR_TRACK_SLOT_CONFLICT
    )
    assert read_session(s3["id"])["state"] == "DRAFT", (
        "A refused schedule must leave the session in DRAFT"
    )
    assert read_track(track["id"])["scheduled_session_count"] == 2, (
        "A refused schedule must not claim a slot"
    )


# ==========================================================================
# Buffered speaker geometry
# ==========================================================================

def _summit_p_speaker_with_two_accepted_sessions():
    """Sessions A 10:00-11:00, B 11:10-12:00 (exactly ten minutes after A) both
    accepted; C 11:09-11:10 is invited but not yet answered."""
    event = new_event(name="Summit P")
    track = add_track(event["id"])
    speaker = add_speaker(event["id"], full_name="Omar Haddad", email="omar@example.com")
    sa = add_session(
        event["id"], track["id"], title="A",
        starts_at="2026-09-26T10:00:00Z", ends_at="2026-09-26T11:00:00Z",
    )
    sb = add_session(
        event["id"], track["id"], title="B",
        starts_at="2026-09-26T11:10:00Z", ends_at="2026-09-26T12:00:00Z",
    )
    sc = add_session(
        event["id"], track["id"], title="C",
        starts_at="2026-09-26T11:09:00Z", ends_at="2026-09-26T11:10:00Z",
    )
    ss_a = invite_speaker(sa["id"], speaker["id"], speaking_role="HOST")
    accept_invitation(ss_a["id"], speaker["id"])
    ss_b = invite_speaker(sb["id"], speaker["id"], speaking_role="PANELIST")
    ss_b_accepted = accept_invitation(ss_b["id"], speaker["id"])
    ss_c = invite_speaker(sc["id"], speaker["id"], speaking_role="PANELIST")
    return event, speaker, ss_a, ss_b_accepted, ss_c


def test_speaker_calendar_accepts_a_gap_of_exactly_ten_minutes(api):
    """PRD 2.10: "A new engagement conflicts with an existing accepted one when
    the new session's `starts_at` is strictly earlier than the other session's
    `ends_at` extended forward by ten minutes **and** the other session's
    `starts_at` is strictly earlier than the new session's `ends_at` extended
    forward by ten minutes. Because both comparisons are strict, a gap of exactly
    ten minutes between two sessions is accepted."

    Design: Difficulty/resource_temporal_overlap/speaker_calendar_buffer_accepts_exactly_ten_minute_gap_rejects_nine
    """
    event, speaker, ss_a, ss_b_accepted, ss_c = _summit_p_speaker_with_two_accepted_sessions()

    assert_session_speaker(ss_b_accepted)
    assert ss_b_accepted["state"] == "ACCEPTED", (
        "An 11:00 -> 11:10 gap is exactly the ten-minute margin and must be accepted; "
        f"got {ss_b_accepted['state']}"
    )
    refreshed = read_speaker(speaker["id"])
    assert_speaker(refreshed)
    assert refreshed["accepted_session_count"] == 2
    assert refreshed["engagement_status"] == "ENGAGED"


def test_speaker_calendar_rejects_a_gap_of_nine_minutes(api):
    """PRD 3.6: "Accepting moves the row `INVITED → ACCEPTED`, requires the
    owning session to be in `DRAFT` or `SCHEDULED`, and enforces the buffered
    speaker geometry of Section 2.10 against every other session for which this
    speaker already holds an `ACCEPTED` row; a clash is
    `ERR_SPEAKER_BUFFER_CONFLICT`."
    PRD 2.10: "An accepted speaking engagement blocks not only its own session
    window but a transition margin of ten minutes on each side, because a human
    speaker cannot appear in two rooms back to back."

    Design: Difficulty/resource_temporal_overlap/speaker_calendar_buffer_accepts_exactly_ten_minute_gap_rejects_nine
    """
    event, speaker, ss_a, ss_b_accepted, ss_c = _summit_p_speaker_with_two_accepted_sessions()

    validate_error(
        api.accept_session_speaker(ss_c["id"], make_speaker_headers(speaker["id"])),
        ApiErrorId.ERR_SPEAKER_BUFFER_CONFLICT,
    )
    assert read_session_speaker(ss_c["id"])["state"] == "INVITED", (
        "A refused acceptance must leave the junction row INVITED"
    )
    assert read_speaker(speaker["id"])["accepted_session_count"] == 2, (
        "A refused acceptance must not raise accepted_session_count"
    )


# ==========================================================================
# The cyclic invite loop
# ==========================================================================

def _summit_f_accepted_invitation():
    """Summit F: a DRAFT session whose invited speaker has accepted."""
    event = new_event(name="Summit F")
    track = add_track(event["id"])
    session = add_session(
        event["id"], track["id"], title="Panel",
        starts_at="2026-09-15T10:00:00Z", ends_at="2026-09-15T11:00:00Z",
    )
    speaker = add_speaker(event["id"], full_name="Ravi Patel", email="ravi@example.com")
    junction = invite_speaker(session["id"], speaker["id"], speaking_role="PANELIST")
    accept_invitation(junction["id"], speaker["id"])
    return event, session, speaker, junction


def test_reinvite_after_withdrawal_bumps_invite_round(api):
    """PRD 3.6: "The organizer may then re-invite, moving the row `WITHDRAWN →
    INVITED` while the session is in `DRAFT` or `SCHEDULED`, which increments
    `invite_round` and changes nothing else."
    PRD 3.6: "The invitation lifecycle is deliberately **cyclic**: `INVITED →
    ACCEPTED → WITHDRAWN → INVITED` may repeat without bound, and `invite_round`
    records how many times the row has entered `INVITED`."

    Design: Difficulty/non_linear_state_machine/session_speaker_withdraw_then_reinvite_completes_invite_cycle
    """
    event, session, speaker, junction = _summit_f_accepted_invitation()
    withdrawn = validate_success(
        api.withdraw_session_speaker(
            junction["id"], make_speaker_headers(speaker["id"])
        ),
        200,
    )
    assert withdrawn["state"] == "WITHDRAWN"
    assert withdrawn["invite_round"] == 1, (
        f"Withdrawal must not bump invite_round, got {withdrawn['invite_round']}"
    )

    reinvited = validate_success(
        api.reinvite_session_speaker(junction["id"], ORG), 200
    )
    assert reinvited["state"] == "INVITED", (
        f"Re-invitation returns the row to INVITED, got {reinvited['state']}"
    )
    assert reinvited["invite_round"] == 2, (
        f"Expected invite_round 2 on the second entry into INVITED, got "
        f"{reinvited['invite_round']}"
    )


def test_second_acceptance_after_reinvite_restores_the_counters(api):
    """PRD 3.6: "On success the speaker's `accepted_session_count` rises by one,
    and because that count is now at least one the speaker's `engagement_status`
    becomes `ENGAGED`; the session's `accepted_speaker_count` also rises by one."
    PRD 3.6: "It reverses the acceptance exactly: the speaker's
    `accepted_session_count` falls by one, and because that count has fallen to
    zero the speaker's `engagement_status` returns to `UNASSIGNED`; the session's
    `accepted_speaker_count` falls by one."

    Design: Difficulty/non_linear_state_machine/session_speaker_withdraw_then_reinvite_completes_invite_cycle
    """
    event, session, speaker, junction = _summit_f_accepted_invitation()
    validate_success(
        api.withdraw_session_speaker(
            junction["id"], make_speaker_headers(speaker["id"])
        ),
        200,
    )
    after_withdraw = read_speaker(speaker["id"])
    assert after_withdraw["accepted_session_count"] == 0
    assert after_withdraw["engagement_status"] == "UNASSIGNED"

    validate_success(api.reinvite_session_speaker(junction["id"], ORG), 200)
    reaccepted = validate_success(
        api.accept_session_speaker(
            junction["id"], make_speaker_headers(speaker["id"])
        ),
        200,
    )
    assert reaccepted["state"] == "ACCEPTED"
    assert reaccepted["invite_round"] == 2, (
        "Re-acceptance leaves invite_round at the value the re-invite set"
    )

    speaker_after = read_speaker(speaker["id"])
    assert speaker_after["accepted_session_count"] == 1
    assert speaker_after["engagement_status"] == "ENGAGED"
    assert read_session(session["id"])["accepted_speaker_count"] == 1


# ==========================================================================
# Corner instances
# ==========================================================================

def test_session_ends_before_starts_returns_time_range_invalid(api):
    """PRD 2.7: "Interval well-formedness — an event's `ends_at` must be strictly
    after its `starts_at`, a session's `ends_at` strictly after its `starts_at`,
    and a match request's `window_end` strictly after its `window_start`;
    otherwise `ERR_TIME_RANGE_INVALID` (HTTP 422). This applies to event
    creation, session creation and match-request creation."

    Design: Corner/validations/corner_session_ends_before_starts_returns_time_range_invalid
    """
    event = new_event(name="Bad Interval")
    track = add_track(event["id"])

    validate_error(
        api.create_session(
            {
                "event_id": event["id"],
                "track_id": track["id"],
                "title": "Backwards",
                "starts_at": "2026-10-27T12:00:00Z",
                "ends_at": "2026-10-27T11:00:00Z",
                "session_type": "LIVE",
                "capacity": 100,
            },
            ORG,
        ),
        ApiErrorId.ERR_TIME_RANGE_INVALID,
    )
    assert read_track(track["id"])["scheduled_session_count"] == 0


def test_session_cancel_releases_track_slot_and_speakers(api):
    """PRD 3.6: "If the prior state was `SCHEDULED` or `LIVE`, the track's
    `scheduled_session_count` drops by one, releasing the slot. Every junction
    row of that session in `INVITED` or `ACCEPTED` moves to `RELEASED`; for rows
    that were `ACCEPTED`, the speaker's `accepted_session_count` falls by one
    with `engagement_status` recomputed, and the session's
    `accepted_speaker_count` falls by one, while rows that were merely `INVITED`
    change no counters."

    Design: Corner/state_machines/corner_session_cancel_releases_track_slot_and_speakers
    """
    event = new_event(name="Release")
    track, session, speaker, junction = setup_session_with_accepted_speaker(
        event["id"],
        session_overrides={
            "title": "Talk",
            "starts_at": "2026-10-12T10:00:00Z",
            "ends_at": "2026-10-12T11:00:00Z",
        },
        speaker_overrides={"full_name": "Ivan Petrov", "email": "ivan@example.com"},
    )
    assert read_track(track["id"])["scheduled_session_count"] == 1

    cancelled = validate_success(
        api.cancel_session(session["id"], "speaker illness", ORG), 200
    )
    assert cancelled["state"] == "CANCELLED"
    assert read_track(track["id"])["scheduled_session_count"] == 0, (
        "Cancelling a SCHEDULED session releases its track slot"
    )
    assert read_session_speaker(junction["id"])["state"] == "RELEASED"
    speaker_after = read_speaker(speaker["id"])
    assert speaker_after["accepted_session_count"] == 0
    assert speaker_after["engagement_status"] == "UNASSIGNED"


def test_decline_from_accepted_session_speaker_is_invalid_transition(api):
    """PRD 3.6: "Declining moves the row `INVITED → DECLINED` and changes no
    counter at all."
    PRD 2.7: "Declared-transition check (`ERR_INVALID_STATE`), then terminal-state
    check (`ERR_ALREADY_TERMINAL`), on every state-transition endpoint."

    Design: Corner/state_machines/corner_decline_from_accepted_session_speaker_is_invalid_transition
    """
    event = new_event(name="Decline Guard")
    track, session, speaker, junction = setup_session_with_accepted_speaker(
        event["id"],
        session_overrides={
            "title": "Talk",
            "starts_at": "2026-10-11T10:00:00Z",
            "ends_at": "2026-10-11T11:00:00Z",
        },
        speaker_overrides={"full_name": "Yuki Sato", "email": "yuki@example.com"},
        schedule=False,
    )

    validate_error(
        api.decline_session_speaker(
            junction["id"], make_speaker_headers(speaker["id"])
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )
    assert read_session_speaker(junction["id"])["state"] == "ACCEPTED"
    assert read_speaker(speaker["id"])["accepted_session_count"] == 1


def test_speaker_cannot_accept_another_speakers_invitation(api):
    """PRD 3.6: "Only the invited `SpeakerUser` — the caller whose `X-User-ID`
    equals the row's `speaker_id` — may accept, decline or withdraw."
    PRD 2.1: "An entity-backed role acting on a resource it does not own, or an
    `Organizer` acting on an event whose `organizer_user_id` differs from the
    acting `X-User-ID`, is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/corner_speaker_cannot_accept_another_speakers_invitation
    """
    event = new_event(name="Ownership")
    track = add_track(event["id"])
    session = add_session(
        event["id"], track["id"], title="Talk",
        starts_at="2026-11-13T10:00:00Z", ends_at="2026-11-13T11:00:00Z",
    )
    speaker_a = add_speaker(event["id"], full_name="Speaker A", email="spa@example.com")
    speaker_b = add_speaker(event["id"], full_name="Speaker B", email="spb@example.com")
    junction = invite_speaker(session["id"], speaker_a["id"], speaking_role="HOST")

    validate_error(
        api.accept_session_speaker(
            junction["id"], make_speaker_headers(speaker_b["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
    )
    assert read_session_speaker(junction["id"])["state"] == "INVITED"
    assert read_speaker(speaker_a["id"])["accepted_session_count"] == 0
    assert read_speaker(speaker_b["id"])["accepted_session_count"] == 0
