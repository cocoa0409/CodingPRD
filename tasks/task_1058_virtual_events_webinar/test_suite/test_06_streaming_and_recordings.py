"""Streaming: the go-live preconditions, the duration ledger, the cyclic
recording lifecycle, on-demand gating and the event-cancellation cascade."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    assert_broadcast,
    assert_recording,
    make_attendee_headers,
    shift_iso,
    api_client,
    new_event,
    add_ticket_type,
    add_track,
    add_session,
    add_speaker,
    invite_speaker,
    accept_invitation,
    schedule_session,
    add_broadcast,
    publish_event,
    start_event,
    add_registration,
    pay_registration,
    set_clock,
    read_event,
    read_session,
    read_speaker,
    read_session_speaker,
    read_broadcast,
    read_recording,
    setup_live_broadcast,
    setup_ended_broadcast,
    setup_ready_recording,
    setup_published_recording,
    setup_on_demand_scenario,
)

ORG = TEST_USERS["organizer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ==========================================================================
# Go-live depends on the owning event
# ==========================================================================

def _summit_m_previewing_broadcast_on_a_published_event():
    """Event never started, so it sits in PUBLISHED while the session is
    SCHEDULED and its broadcast is in PREVIEW."""
    event = new_event(name="Summit M")
    add_ticket_type(event["id"])
    track = add_track(event["id"])
    session = add_session(
        event["id"], track["id"], title="Keynote", capacity=400,
        starts_at="2026-09-23T10:00:00Z", ends_at="2026-09-23T11:00:00Z",
    )
    speaker = add_speaker(event["id"], full_name="Lena Ford", email="lena@example.com")
    junction = invite_speaker(session["id"], speaker["id"], speaking_role="HOST")
    accept_invitation(junction["id"], speaker["id"])
    session = schedule_session(session["id"])
    broadcast = add_broadcast(session["id"], ingest_region="US_WEST")
    publish_event(event["id"])
    broadcast = validate_success(
        api_client.preview_broadcast(broadcast["id"], ORG), 200
    )
    return event, session, speaker, broadcast


def test_go_live_is_refused_while_the_owning_event_is_not_live(api):
    """PRD 3.7: "It moves the broadcast `PREVIEW → LIVE` and demands three things
    at once: the owning session must still be `SCHEDULED`, the owning **event**
    must be `LIVE`, and the session must have at least one accepted speaker —
    that is, its `accepted_speaker_count` must be one or more. A failure on any
    of those three is `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/broadcast_go_live_requires_owning_event_to_be_live
    """
    event, session, speaker, broadcast = _summit_m_previewing_broadcast_on_a_published_event()
    assert read_event(event["id"])["state"] == "PUBLISHED", (
        "Setup must leave the event short of LIVE"
    )
    assert read_session(session["id"])["accepted_speaker_count"] == 1, (
        "Setup must satisfy the accepted-speaker precondition so only the event "
        "state can fail"
    )

    validate_error(
        api.go_live_broadcast(broadcast["id"], ORG), ApiErrorId.ERR_INVALID_STATE
    )


def test_refused_go_live_leaves_the_broadcast_and_session_untouched(api):
    """PRD 3.7: "On success the broadcast's `started_at` is stamped with the
    current logical clock, the session transitions `SCHEDULED → LIVE`, and a
    recording row is created in `PENDING` with its `broadcast_id`, `session_id`
    and `event_id` all populated from the producing broadcast and its ancestors."
    PRD 3.7: "The organizer creates one against a `session_id` with an
    `ingest_region` of `US_EAST`, `US_WEST`, `EU_WEST` or `AP_SOUTH`, and it
    lands in `SCHEDULED` with `started_at`, `ended_at` both null and
    `streamed_minutes` at zero."

    Design: Difficulty/cross_entity_state_dependency/broadcast_go_live_requires_owning_event_to_be_live
    """
    event, session, speaker, broadcast = _summit_m_previewing_broadcast_on_a_published_event()
    validate_error(
        api.go_live_broadcast(broadcast["id"], ORG), ApiErrorId.ERR_INVALID_STATE
    )

    refreshed = read_broadcast(broadcast["id"])
    assert_broadcast(refreshed)
    assert refreshed["state"] == "PREVIEW", (
        f"A refused go-live must leave the broadcast in PREVIEW, got {refreshed['state']}"
    )
    assert refreshed["started_at"] is None, (
        "started_at is only stamped on a successful go-live"
    )
    assert read_session(session["id"])["state"] == "SCHEDULED", (
        "A refused go-live must not advance the session"
    )
    rows, meta = validate_paginated(
        api.list_recordings(ORG, params={"broadcast_id": broadcast["id"]})
    )
    assert meta["total_count"] == 0, (
        "No recording exists until a broadcast actually goes live"
    )


# ==========================================================================
# The event-cancellation cascade
# ==========================================================================

def test_event_cancel_cascades_through_session_broadcast_and_recording(api):
    """PRD 3.1: "From `PUBLISHED` or `LIVE` the same first link fires and then
    propagates two links further. Every broadcast belonging to one of those newly
    cancelled sessions and sitting in `SCHEDULED`, `PREVIEW` or `LIVE` becomes
    `ABORTED`. Then, because those broadcasts aborted, every recording they
    produced that sits in `PENDING`, `PROCESSING`, `READY` or `PUBLISHED` becomes
    `RETRACTED`, and for each such recording that had been `PUBLISHED`, the
    event's `published_recording_count` is decremented by one."

    Design: Difficulty/transitive_cascade/event_cancel_chains_session_to_broadcast_to_recording
    """
    ctx = setup_live_broadcast(
        event_overrides={"name": "Summit G"},
        session_overrides={
            "title": "Keynote", "capacity": 500,
            "starts_at": "2026-09-16T10:00:00Z", "ends_at": "2026-09-16T11:00:00Z",
        },
        ingest_region="EU_WEST",
    )
    assert ctx["recording"]["state"] == "PENDING"

    cancelled = validate_success(
        api.cancel_event(ctx["event"]["id"], "venue platform outage", ORG), 200
    )
    assert cancelled["state"] == "CANCELLED"
    assert read_session(ctx["session"]["id"])["state"] == "CANCELLED", (
        "Cascade link 1: the session is cancelled"
    )
    assert read_broadcast(ctx["broadcast"]["id"])["state"] == "ABORTED", (
        "Cascade link 2: the LIVE broadcast is aborted"
    )
    assert read_recording(ctx["recording"]["id"])["state"] == "RETRACTED", (
        "Cascade link 3: the PENDING recording is retracted"
    )


def test_event_cancel_releases_the_speakers_the_cascade_touched(api):
    """PRD 3.6: "Every junction row of that session in `INVITED` or `ACCEPTED`
    moves to `RELEASED`; for rows that were `ACCEPTED`, the speaker's
    `accepted_session_count` falls by one with `engagement_status` recomputed,
    and the session's `accepted_speaker_count` falls by one, while rows that were
    merely `INVITED` change no counters."
    PRD 3.6: "A speaker's `engagement_status` is purely derived: it reads
    `ENGAGED` whenever `accepted_session_count` is one or more, and `UNASSIGNED`
    otherwise."

    Design: Difficulty/transitive_cascade/event_cancel_chains_session_to_broadcast_to_recording
    """
    ctx = setup_live_broadcast(
        event_overrides={"name": "Summit G"},
        session_overrides={
            "title": "Keynote", "capacity": 500,
            "starts_at": "2026-09-16T10:00:00Z", "ends_at": "2026-09-16T11:00:00Z",
        },
        ingest_region="EU_WEST",
    )
    validate_success(
        api.cancel_event(ctx["event"]["id"], "venue platform outage", ORG), 200
    )

    assert read_session_speaker(ctx["session_speaker"]["id"])["state"] == "RELEASED"
    speaker = read_speaker(ctx["speaker"]["id"])
    assert speaker["accepted_session_count"] == 0
    assert speaker["engagement_status"] == "UNASSIGNED"
    assert read_event(ctx["event"]["id"])["published_recording_count"] == 0, (
        "No recording had been published, so the counter stays at zero"
    )


# ==========================================================================
# Corner instances
# ==========================================================================

def test_broadcast_end_computes_streamed_minutes_and_completes_session(api):
    """PRD 3.7: "Its `ended_at` is stamped with the current logical clock, and
    its `streamed_minutes` is computed as the elapsed time from `started_at` to
    `ended_at` expressed in whole minutes, discarding any remainder — a stream
    lasting fifty-nine seconds bills zero minutes. That figure is added to the
    owning event's `streamed_minutes_total`, the session transitions `LIVE →
    COMPLETED`, the broadcast's recording moves `PENDING → PROCESSING`, and the
    event's `version` advances."

    Design: Corner/state_machines/corner_broadcast_end_computes_streamed_minutes_and_completes_session
    """
    ctx = setup_live_broadcast(
        event_overrides={"name": "Ledger"},
        session_overrides={
            "title": "Keynote",
            "starts_at": "2026-10-13T10:00:00Z", "ends_at": "2026-10-13T11:00:00Z",
        },
        ingest_region="AP_SOUTH",
    )
    set_clock(shift_iso(ctx["broadcast"]["started_at"], minutes=45))

    ended = validate_success(api.end_broadcast(ctx["broadcast"]["id"], ORG), 200)
    assert_broadcast(ended)
    assert ended["streamed_minutes"] == 45, (
        f"45 elapsed minutes must bill 45, got {ended['streamed_minutes']}"
    )
    assert ended["state"] == "ENDED"
    assert read_event(ctx["event"]["id"])["streamed_minutes_total"] == 45
    assert read_session(ctx["session"]["id"])["state"] == "COMPLETED"
    assert read_recording(ctx["recording"]["id"])["state"] == "PROCESSING"


def test_recording_retract_then_reprocess_reenters_processing(api):
    """PRD 3.7: "Retraction, taking a `reason`, moves the recording `PUBLISHED →
    RETRACTED`, decrements `published_recording_count`, and closes the asset to
    further viewing. A platform admin may reprocess a `RETRACTED` recording back
    to `PROCESSING`, which resets its `duration_seconds` to zero and starts the
    encode cycle over."

    Design: Corner/state_machines/corner_recording_retract_then_reprocess_reenters_processing
    """
    ctx = setup_published_recording(
        gating_level="ON_DEMAND", duration_seconds=3600, minutes=60,
        event_overrides={"name": "Recycle"},
        session_overrides={
            "title": "Keynote",
            "starts_at": "2026-10-14T10:00:00Z", "ends_at": "2026-10-14T11:00:00Z",
        },
    )
    assert read_event(ctx["event"]["id"])["published_recording_count"] == 1

    retracted = validate_success(
        api.retract_recording(ctx["recording"]["id"], "wrong cut", ORG), 200
    )
    assert retracted["state"] == "RETRACTED"

    reprocessed = validate_success(
        api.reprocess_recording(ctx["recording"]["id"], ADMIN), 200
    )
    assert_recording(reprocessed)
    assert reprocessed["state"] == "PROCESSING", (
        f"Reprocessing returns the row to PROCESSING, got {reprocessed['state']}"
    )
    assert reprocessed["duration_seconds"] == 0, (
        f"Reprocessing resets duration_seconds to zero, got "
        f"{reprocessed['duration_seconds']}"
    )
    assert read_event(ctx["event"]["id"])["published_recording_count"] == 0


def test_delete_ready_recording_returns_204_and_hides_row(api):
    """PRD 3.7: "Deletion is a soft operation available from `RETRACTED` or
    `READY`: the row moves to `DELETED` and thereafter is excluded from list
    results and answers individual reads with `ERR_RECORDING_NOT_FOUND`, unless a
    list request explicitly asks for the `DELETED` state."
    PRD 4: "the soft-delete of a recording answers with **204 No Content** and an
    empty body."

    Design: Corner/endpoints/corner_delete_ready_recording_returns_204_and_hides_row
    """
    ctx = setup_ready_recording(
        duration_seconds=1800, minutes=30,
        event_overrides={"name": "Soft Delete"},
        session_overrides={
            "title": "Keynote",
            "starts_at": "2026-11-08T10:00:00Z", "ends_at": "2026-11-08T11:00:00Z",
        },
        ingest_region="EU_WEST",
    )
    assert ctx["recording"]["state"] == "READY"

    response = api.delete_recording(ctx["recording"]["id"], ORG)
    assert response.status_code == 204, (
        f"Expected 204 No Content from the soft-delete, got {response.status_code}"
    )

    rows, meta = validate_paginated(
        api.list_recordings(ORG, params={"broadcast_id": ctx["broadcast"]["id"]})
    )
    assert meta["total_count"] == 0, (
        f"A DELETED recording is excluded from the default list, got total_count "
        f"{meta['total_count']}"
    )
    assert rows == []

    deleted_rows, _ = validate_paginated(
        api.list_recordings(
            ORG,
            params={"broadcast_id": ctx["broadcast"]["id"], "state": "DELETED"},
        )
    )
    assert [r["id"] for r in deleted_rows] == [ctx["recording"]["id"]], (
        "The row is still reachable when the list explicitly asks for DELETED"
    )
    assert deleted_rows[0]["state"] == "DELETED"


def test_live_only_ticket_cannot_view_on_demand_recording(api):
    """PRD 3.7: "An `Attendee` registers a view by naming their
    `registration_id`, and two conditions must hold: the ticket type behind that
    registration must carry a `gating_level` of `ON_DEMAND` or `BOTH` — a
    `LIVE_ONLY` ticket buys no replay rights — and the registration's
    `payment_status` must be `PAID`. Either failure yields
    `ERR_GATING_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/validations/corner_live_only_ticket_cannot_view_on_demand_recording
    """
    ctx = setup_on_demand_scenario(
        ticket_gating_level="LIVE_ONLY",
        recording_gating_level="ON_DEMAND",
        pay=True,
        attendee_email="gated@example.com",
        duration_seconds=3600,
        minutes=60,
        event_overrides={"name": "Gated"},
        session_overrides={
            "title": "Keynote",
            "starts_at": "2026-11-06T10:00:00Z", "ends_at": "2026-11-06T11:00:00Z",
        },
    )
    registration = ctx["registration"]
    assert registration["payment_status"] == "PAID", (
        "Setup must satisfy the PAID half of the gate so only the ticket's "
        "gating_level can fail"
    )

    validate_error(
        api.record_recording_view(
            ctx["recording"]["id"], registration["id"],
            make_attendee_headers(registration["id"]),
        ),
        ApiErrorId.ERR_GATING_NOT_PERMITTED,
    )
    recording = read_recording(ctx["recording"]["id"])
    assert recording["view_count"] == 0, (
        "A refused view must not increment view_count"
    )
    assert recording["state"] == "PUBLISHED"
    assert read_event(ctx["event"]["id"])["published_recording_count"] == 1
