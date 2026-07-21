"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch using only endpoints the PRD declares. Setup calls
use the lenient success validator so a broken precondition surfaces as a clear
setup failure rather than as a confusing assertion further down.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_UTC,
    TEST_DEFAULTS,
    FINANCE_ADMIN_USER_ID,
    ORGANIZER_USER_ID,
)
from .factories import (
    create_event_payload,
    create_ticket_type_payload,
    create_registration_payload,
    create_track_payload,
    create_session_payload,
    create_speaker_payload,
    create_session_speaker_payload,
    create_broadcast_payload,
    create_sponsor_payload,
    create_booth_payload,
    create_match_request_payload,
)
from .test_users import (
    make_organizer_headers,
    make_platform_admin_headers,
    make_finance_admin_headers,
    make_attendee_headers,
    make_speaker_headers,
    make_sponsor_headers,
)

ORG = make_organizer_headers()
ADMIN = make_platform_admin_headers()
FIN = make_finance_admin_headers()


# ==========================================================================
# Tier 0 - single-call primitives
# ==========================================================================

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock. Returns the clock payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def reset_clock() -> dict:
    """Pin the logical clock at its documented starting instant."""
    return set_clock(DEFAULT_CLOCK_UTC)


def new_event(organizer_user_id: str = ORGANIZER_USER_ID, **overrides) -> dict:
    headers = make_organizer_headers(organizer_user_id)
    return get_success_data(
        api_client.create_event(create_event_payload(**overrides), headers)
    )


def add_ticket_type(event_id: str, organizer_user_id: str = ORGANIZER_USER_ID, **overrides) -> dict:
    headers = make_organizer_headers(organizer_user_id)
    return get_success_data(
        api_client.create_ticket_type(
            event_id, create_ticket_type_payload(**overrides), headers
        )
    )


def publish_event(event_id: str, organizer_user_id: str = ORGANIZER_USER_ID) -> dict:
    return get_success_data(
        api_client.publish_event(event_id, make_organizer_headers(organizer_user_id))
    )


def start_event(event_id: str, organizer_user_id: str = ORGANIZER_USER_ID) -> dict:
    return get_success_data(
        api_client.start_event(event_id, make_organizer_headers(organizer_user_id))
    )


def end_event(event_id: str, organizer_user_id: str = ORGANIZER_USER_ID) -> dict:
    return get_success_data(
        api_client.end_event(event_id, make_organizer_headers(organizer_user_id))
    )


def read_event(event_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_event(event_id, headers or ORG))


def read_ticket_type(ticket_type_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_ticket_type(ticket_type_id, headers or ORG))


def read_registration(registration_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_registration(registration_id, headers or ORG)
    )


def read_session(session_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_session(session_id, headers or ORG))


def read_speaker(speaker_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_speaker(speaker_id, headers or ORG))


def read_session_speaker(session_speaker_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_session_speaker(session_speaker_id, headers or ORG)
    )


def read_track(track_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_track(track_id, headers or ORG))


def read_broadcast(broadcast_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_broadcast(broadcast_id, headers or ORG))


def read_recording(recording_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_recording(recording_id, headers or ORG))


def read_booth(booth_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_booth(booth_id, headers or ORG))


def read_sponsor(sponsor_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sponsor(sponsor_id, headers or ORG))


def read_lead(lead_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_lead(lead_id, headers or ORG))


def read_match_request(match_request_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_match_request(match_request_id, headers or ORG)
    )


def read_settlement(settlement_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, headers or FIN))


def add_registration(event_id: str, ticket_type_id: str, attendee_email: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_registration(
            create_registration_payload(
                event_id, ticket_type_id, attendee_email, **overrides
            ),
            ORG,
        )
    )


def pay_registration(registration_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.pay_registration(registration_id, amount_cents, ORG)
    )


def check_in(registration_id: str) -> dict:
    return get_success_data(api_client.check_in_registration(registration_id, ORG))


def record_watch_minutes(session_id: str, registration_id: str, minutes: int) -> dict:
    return get_success_data(
        api_client.record_session_attendance(session_id, registration_id, minutes, ORG)
    )


def add_track(event_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_track(event_id, create_track_payload(**overrides), ORG)
    )


def add_session(event_id: str, track_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_session(
            create_session_payload(event_id, track_id, **overrides), ORG
        )
    )


def schedule_session(session_id: str) -> dict:
    return get_success_data(api_client.schedule_session(session_id, ORG))


def add_speaker(event_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_speaker(event_id, create_speaker_payload(**overrides), ORG)
    )


def invite_speaker(session_id: str, speaker_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_session_speaker(
            create_session_speaker_payload(session_id, speaker_id, **overrides), ORG
        )
    )


def accept_invitation(session_speaker_id: str, speaker_id: str) -> dict:
    return get_success_data(
        api_client.accept_session_speaker(
            session_speaker_id, make_speaker_headers(speaker_id)
        )
    )


def add_broadcast(session_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_broadcast(create_broadcast_payload(session_id, **overrides), ORG)
    )


def add_sponsor(event_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_sponsor(event_id, create_sponsor_payload(**overrides), ORG)
    )


def sign_contract(sponsor_id: str, signed_by: str = "Legal") -> dict:
    return get_success_data(
        api_client.sign_sponsor_contract(sponsor_id, signed_by, ORG)
    )


def add_booth(sponsor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_booth(
            create_booth_payload(sponsor_id, **overrides), make_sponsor_headers(sponsor_id)
        )
    )


def submit_booth(booth_id: str, sponsor_id: str) -> dict:
    return get_success_data(
        api_client.submit_booth(booth_id, make_sponsor_headers(sponsor_id))
    )


def approve_booth(booth_id: str) -> dict:
    return get_success_data(api_client.approve_booth(booth_id, ORG))


def capture_lead(booth_id: str, registration_id: str, marketing_consent: bool = True) -> dict:
    return get_success_data(
        api_client.capture_lead(
            booth_id, registration_id, marketing_consent,
            make_attendee_headers(registration_id),
        )
    )


def log_interaction(lead_id: str, sponsor_id: str, interaction_type: str) -> dict:
    return get_success_data(
        api_client.log_lead_interaction(
            lead_id, interaction_type, make_sponsor_headers(sponsor_id)
        )
    )


def add_match_request(event_id, requester_registration_id, target_registration_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_match_request(
            create_match_request_payload(
                event_id, requester_registration_id, target_registration_id, **overrides
            ),
            make_attendee_headers(requester_registration_id),
        )
    )


def accept_match_request(match_request_id: str, target_registration_id: str) -> dict:
    return get_success_data(
        api_client.accept_match_request(
            match_request_id, make_attendee_headers(target_registration_id)
        )
    )


def find_recording_for_broadcast(broadcast_id: str) -> dict:
    """Recordings are never created by a client; locate the row the broadcast
    produced when it went live."""
    data = get_success_data(
        api_client.list_recordings(ORG, params={"broadcast_id": broadcast_id})
    )
    assert data, f"Setup failed: no recording exists for broadcast {broadcast_id}"
    return data[0]


# ==========================================================================
# Tier 1 - state progression on the event
# ==========================================================================

def setup_published_event(event_overrides=None, ticket_overrides=None):
    """DRAFT event + one ticket type + publish. Returns (event, ticket_type).

    The returned event dict is the response to the publish call, so its state is
    PUBLISHED and its version reflects both the ticket-type creation and the
    publish.
    """
    event = new_event(**(event_overrides or {}))
    ticket_type = add_ticket_type(event["id"], **(ticket_overrides or {}))
    event = publish_event(event["id"])
    return event, ticket_type


def setup_live_event(event_overrides=None, ticket_overrides=None):
    """Event driven DRAFT -> PUBLISHED -> LIVE. Returns (event, ticket_type)."""
    event, ticket_type = setup_published_event(event_overrides, ticket_overrides)
    event = start_event(event["id"])
    return event, ticket_type


def setup_ended_event(event_overrides=None, ticket_overrides=None):
    """Event driven all the way to ENDED. Returns (event, ticket_type)."""
    event, ticket_type = setup_live_event(event_overrides, ticket_overrides)
    event = end_event(event["id"])
    return event, ticket_type


# ==========================================================================
# Tier 2 - registration hierarchies
# ==========================================================================

def setup_event_with_registration(
    attendee_email="attendee@example.com",
    event_overrides=None,
    ticket_overrides=None,
    registration_overrides=None,
):
    """PUBLISHED event + ticket type + one seat-holding registration.
    Returns (event, ticket_type, registration)."""
    event, ticket_type = setup_published_event(event_overrides, ticket_overrides)
    registration = add_registration(
        event["id"], ticket_type["id"], attendee_email,
        **(registration_overrides or {}),
    )
    return event, ticket_type, registration


def setup_paid_registration(
    attendee_email="paid@example.com",
    amount_cents=None,
    event_overrides=None,
    ticket_overrides=None,
    registration_overrides=None,
):
    """PUBLISHED event + one registration paid in full.
    Returns (event, ticket_type, registration)."""
    event, ticket_type, registration = setup_event_with_registration(
        attendee_email, event_overrides, ticket_overrides, registration_overrides
    )
    due = registration["amount_due_cents"] if amount_cents is None else amount_cents
    registration = pay_registration(registration["id"], due)
    return event, ticket_type, registration


def setup_checked_in_registration(
    watched_minutes=0,
    attendee_email="checkedin@example.com",
    event_overrides=None,
    ticket_overrides=None,
    session_overrides=None,
):
    """LIVE event + track + session + one CHECKED_IN registration carrying
    ``watched_minutes`` of accumulated viewing time.
    Returns (event, ticket_type, registration, session)."""
    event, ticket_type = setup_published_event(event_overrides, ticket_overrides)
    track = add_track(event["id"])
    session = add_session(event["id"], track["id"], **(session_overrides or {}))
    registration = add_registration(event["id"], ticket_type["id"], attendee_email)
    event = start_event(event["id"])
    registration = check_in(registration["id"])
    if watched_minutes:
        registration = record_watch_minutes(
            session["id"], registration["id"], watched_minutes
        )
    return event, ticket_type, registration, session


# ==========================================================================
# Tier 3 - the programme: tracks, sessions, speakers, broadcasts
# ==========================================================================

def setup_session_with_accepted_speaker(
    event_id,
    session_overrides=None,
    speaker_overrides=None,
    speaking_role="HOST",
    schedule=True,
):
    """Track + session + speaker + an ACCEPTED junction row, optionally with the
    session scheduled onto the track.
    Returns (track, session, speaker, session_speaker)."""
    track = add_track(event_id)
    session = add_session(event_id, track["id"], **(session_overrides or {}))
    speaker = add_speaker(event_id, **(speaker_overrides or {}))
    session_speaker = invite_speaker(
        session["id"], speaker["id"], speaking_role=speaking_role
    )
    session_speaker = accept_invitation(session_speaker["id"], speaker["id"])
    if schedule:
        session = schedule_session(session["id"])
    return track, session, speaker, session_speaker


def setup_live_broadcast(
    event_overrides=None,
    ticket_overrides=None,
    session_overrides=None,
    ingest_region="US_EAST",
):
    """Full chain to a LIVE broadcast: event with a ticket type, a scheduled
    session carrying an accepted speaker, event started, broadcast previewed and
    taken live. A recording row exists in PENDING at that point.

    Returns a dict with event, ticket_type, track, session, speaker,
    session_speaker, broadcast and recording.
    """
    event = new_event(**(event_overrides or {}))
    ticket_type = add_ticket_type(event["id"], **(ticket_overrides or {}))
    track, session, speaker, session_speaker = setup_session_with_accepted_speaker(
        event["id"], session_overrides=session_overrides
    )
    broadcast = add_broadcast(session["id"], ingest_region=ingest_region)
    event = publish_event(event["id"])
    event = start_event(event["id"])
    get_success_data(api_client.preview_broadcast(broadcast["id"], ORG))
    broadcast = get_success_data(api_client.go_live_broadcast(broadcast["id"], ORG))
    recording = find_recording_for_broadcast(broadcast["id"])
    return {
        "event": event,
        "ticket_type": ticket_type,
        "track": track,
        "session": session,
        "speaker": speaker,
        "session_speaker": session_speaker,
        "broadcast": broadcast,
        "recording": recording,
    }


def setup_ended_broadcast(minutes=30, **kwargs):
    """As ``setup_live_broadcast`` then advance the clock by ``minutes`` and end
    the stream, so the broadcast is ENDED and its recording is PROCESSING."""
    ctx = setup_live_broadcast(**kwargs)
    started_at = ctx["broadcast"]["started_at"]
    from .assertions import shift_iso

    set_clock(shift_iso(started_at, minutes=minutes))
    ctx["broadcast"] = get_success_data(
        api_client.end_broadcast(ctx["broadcast"]["id"], ORG)
    )
    ctx["recording"] = read_recording(ctx["recording"]["id"])
    ctx["event"] = read_event(ctx["event"]["id"])
    ctx["session"] = read_session(ctx["session"]["id"])
    return ctx


def setup_ready_recording(duration_seconds=3600, minutes=30, **kwargs):
    """As ``setup_ended_broadcast`` then complete media processing, leaving the
    recording READY with the supplied duration."""
    ctx = setup_ended_broadcast(minutes=minutes, **kwargs)
    ctx["recording"] = get_success_data(
        api_client.complete_recording(ctx["recording"]["id"], duration_seconds, ADMIN)
    )
    return ctx


def setup_published_recording(gating_level="ON_DEMAND", duration_seconds=3600, **kwargs):
    """As ``setup_ready_recording`` then publish, so the recording is PUBLISHED
    and the event's published_recording_count is 1."""
    ctx = setup_ready_recording(duration_seconds=duration_seconds, **kwargs)
    ctx["recording"] = get_success_data(
        api_client.publish_recording(ctx["recording"]["id"], gating_level, ORG)
    )
    ctx["event"] = read_event(ctx["event"]["id"])
    return ctx


def setup_on_demand_scenario(
    ticket_gating_level="BOTH",
    recording_gating_level="ON_DEMAND",
    pay=True,
    attendee_email="viewer@example.com",
    duration_seconds=3600,
    minutes=60,
    event_overrides=None,
    session_overrides=None,
):
    """A PUBLISHED recording plus a registration bought while the registration
    window was still open, so on-demand gating can be exercised end to end.

    The seat is taken before the event starts because registration is refused
    once the event is LIVE. Returns a dict with event, ticket_type, session,
    broadcast, recording and registration.
    """
    event = new_event(**(event_overrides or {}))
    ticket_type = add_ticket_type(event["id"], gating_level=ticket_gating_level)
    track, session, speaker, session_speaker = setup_session_with_accepted_speaker(
        event["id"], session_overrides=session_overrides
    )
    broadcast = add_broadcast(session["id"])
    event = publish_event(event["id"])
    registration = add_registration(event["id"], ticket_type["id"], attendee_email)
    if pay:
        registration = pay_registration(
            registration["id"], registration["amount_due_cents"]
        )
    event = start_event(event["id"])
    get_success_data(api_client.preview_broadcast(broadcast["id"], ORG))
    broadcast = get_success_data(api_client.go_live_broadcast(broadcast["id"], ORG))
    recording = find_recording_for_broadcast(broadcast["id"])

    from .assertions import shift_iso

    set_clock(shift_iso(broadcast["started_at"], minutes=minutes))
    broadcast = get_success_data(api_client.end_broadcast(broadcast["id"], ORG))
    recording = get_success_data(
        api_client.complete_recording(recording["id"], duration_seconds, ADMIN)
    )
    recording = get_success_data(
        api_client.publish_recording(recording["id"], recording_gating_level, ORG)
    )
    return {
        "event": read_event(event["id"]),
        "ticket_type": ticket_type,
        "track": track,
        "session": read_session(session["id"]),
        "speaker": speaker,
        "broadcast": broadcast,
        "recording": recording,
        "registration": read_registration(registration["id"]),
    }


# ==========================================================================
# Tier 4 - sponsorship graph
# ==========================================================================

def setup_sponsor_with_booth(event_id, sponsor_overrides=None, booth_overrides=None,
                             sign=True, submit=True, approve=True):
    """Sponsor (optionally SIGNED) plus a booth walked as far through the review
    workflow as the flags allow. Returns (sponsor, booth)."""
    sponsor = add_sponsor(event_id, **(sponsor_overrides or {}))
    if sign:
        sponsor = sign_contract(sponsor["id"])
    booth = add_booth(sponsor["id"], **(booth_overrides or {}))
    if submit:
        booth = submit_booth(booth["id"], sponsor["id"])
    if approve:
        booth = approve_booth(booth["id"])
    return sponsor, booth


def setup_live_booth_with_lead(
    watched_minutes=0,
    attendee_email="lead@example.com",
    sponsor_overrides=None,
    booth_overrides=None,
    pay=True,
):
    """LIVE event, signed sponsor, booth approved and promoted to LIVE by the
    event start, one CHECKED_IN registration with the requested watch minutes,
    and one lead captured at the booth.

    Returns a dict with event, ticket_type, session, registration, sponsor,
    booth and lead.
    """
    event = new_event()
    ticket_type = add_ticket_type(event["id"])
    track = add_track(event["id"])
    session = add_session(
        event["id"], track["id"], title="Marathon",
        starts_at="2026-09-10T10:00:00Z", ends_at="2026-09-10T16:00:00Z",
    )
    sponsor, booth = setup_sponsor_with_booth(
        event["id"], sponsor_overrides, booth_overrides
    )
    event = publish_event(event["id"])
    registration = add_registration(event["id"], ticket_type["id"], attendee_email)
    if pay:
        registration = pay_registration(registration["id"], registration["amount_due_cents"])
    event = start_event(event["id"])
    registration = check_in(registration["id"])
    if watched_minutes:
        registration = record_watch_minutes(
            session["id"], registration["id"], watched_minutes
        )
    lead = capture_lead(booth["id"], registration["id"], True)
    return {
        "event": event,
        "ticket_type": ticket_type,
        "track": track,
        "session": session,
        "registration": registration,
        "sponsor": sponsor,
        "booth": booth,
        "lead": lead,
    }


# ==========================================================================
# Tier 5 - billing and terminal states
# ==========================================================================

def current_event_version(event_id: str) -> int:
    """Read the event's live version, as a settlement client must before it
    supplies expected_event_version."""
    return read_event(event_id, FIN)["version"]


def create_event_settlement(event_id: str, finance_user_id=FINANCE_ADMIN_USER_ID) -> dict:
    """Create the EVENT settlement with a freshly read version."""
    headers = make_finance_admin_headers(finance_user_id)
    version = current_event_version(event_id)
    return get_success_data(
        api_client.create_event_settlement(event_id, version, headers)
    )


def setup_event_settlement(event_overrides=None, ticket_overrides=None):
    """Event driven to ENDED with no paid registrations, plus its DRAFT EVENT
    settlement. Returns (event, ticket_type, settlement)."""
    event, ticket_type = setup_ended_event(event_overrides, ticket_overrides)
    settlement = create_event_settlement(event["id"])
    return event, ticket_type, settlement


def setup_issued_event_settlement(issuer_user_id=FINANCE_ADMIN_USER_ID, **kwargs):
    """As ``setup_event_settlement`` then issue it, which also moves the event
    ENDED -> SETTLED. Returns (event, ticket_type, settlement)."""
    event, ticket_type, settlement = setup_event_settlement(**kwargs)
    settlement = get_success_data(
        api_client.issue_settlement(
            settlement["id"], make_finance_admin_headers(issuer_user_id)
        )
    )
    return event, ticket_type, settlement

