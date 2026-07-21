"""Networking: closed meeting windows, the one-hour expiry lead and the
organizer-triggered sweep."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_match_request,
    assert_same_instant,
    make_attendee_headers,
    set_clock,
    add_registration,
    add_match_request,
    accept_match_request,
    read_match_request,
    read_registration,
    setup_published_event,
)

ORG = TEST_USERS["organizer_headers"]


def test_matchmaking_sweep_expires_stale_pending_request(api):
    """PRD 3.9: "A new request lands in `PENDING`, and its `expires_at` is
    derived as the `window_start` less one hour."
    PRD 3.9: "Requests that nobody answered are cleared by an
    organizer-triggered sweep over a single event, which moves every `PENDING`
    request of that event whose `expires_at` is at or before the current logical
    clock to `EXPIRED` and returns the `expired_count` of rows it touched."

    Design: Corner/state_machines/corner_matchmaking_sweep_expires_stale_pending_request
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Sweep"})
    r1 = add_registration(event["id"], ticket_type["id"], "m1@example.com")
    r2 = add_registration(event["id"], ticket_type["id"], "m2@example.com")
    request = add_match_request(
        event["id"], r1["id"], r2["id"],
        window_start="2026-10-19T12:00:00Z", window_end="2026-10-19T13:00:00Z",
    )
    assert_match_request(request)
    assert_same_instant(
        request["expires_at"], "2026-10-19T11:00:00Z", "expires_at"
    )
    set_clock("2026-10-19T11:00:00Z")

    result = validate_success(api.sweep_matchmaking(event["id"], ORG), 200)
    assert result["expired_count"] == 1, (
        f"The request is exactly at its expiry instant, so it sweeps; got "
        f"{result['expired_count']}"
    )
    assert read_match_request(request["id"])["state"] == "EXPIRED"


def test_self_match_request_returns_self_match_not_allowed(api):
    """PRD 3.9: "A registration may not propose a meeting with itself —
    identical requester and target identifiers are refused with
    `ERR_SELF_MATCH_NOT_ALLOWED` (HTTP 422) — and both registrations must belong
    to the named event, or the proposal fails with
    `ERR_REGISTRATION_EVENT_MISMATCH`."

    Design: Corner/validations/corner_self_match_request_returns_self_match_not_allowed
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Self Match"})
    r1 = add_registration(event["id"], ticket_type["id"], "solo@example.com")

    validate_error(
        api.create_match_request(
            {
                "event_id": event["id"],
                "requester_registration_id": r1["id"],
                "target_registration_id": r1["id"],
                "window_start": "2026-10-30T12:00:00Z",
                "window_end": "2026-10-30T13:00:00Z",
            },
            make_attendee_headers(r1["id"]),
        ),
        ApiErrorId.ERR_SELF_MATCH_NOT_ALLOWED,
    )
    assert read_registration(r1["id"])["accepted_meeting_count"] == 0


def test_match_accept_at_expiry_instant_returns_expired(api):
    """PRD 3.9: "The current logical clock must be strictly before `expires_at`;
    at or past that instant the attempt is refused with
    `ERR_MATCH_REQUEST_EXPIRED` (HTTP 409)."

    Design: Corner/validations/corner_match_accept_at_expiry_instant_returns_expired
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Late Accept"})
    r1 = add_registration(event["id"], ticket_type["id"], "la1@example.com")
    r2 = add_registration(event["id"], ticket_type["id"], "la2@example.com")
    request = add_match_request(
        event["id"], r1["id"], r2["id"],
        window_start="2026-11-02T12:00:00Z", window_end="2026-11-02T13:00:00Z",
    )
    set_clock("2026-11-02T11:00:00Z")

    validate_error(
        api.accept_match_request(request["id"], make_attendee_headers(r2["id"])),
        ApiErrorId.ERR_MATCH_REQUEST_EXPIRED,
    )
    assert read_match_request(request["id"])["state"] == "PENDING", (
        "A refused acceptance leaves the request PENDING"
    )
    assert read_registration(r2["id"])["accepted_meeting_count"] == 0


def test_meeting_windows_touching_at_an_endpoint_conflict(api):
    """PRD 2.10: "Two accepted meetings for the same participant conflict when
    the new meeting's `window_start` is at or before the other's `window_end`
    **and** the other's `window_start` is at or before the new meeting's
    `window_end`. Because the interval is closed, meetings that merely touch at
    an endpoint — one ending exactly when the other begins — **do** conflict."
    PRD 3.9: "And neither the requester's nor the target's calendar may already
    hold an accepted meeting whose closed window intersects this one under the
    geometry of Section 2.10 — each participant may hold at most one accepted
    meeting at any instant, so an intersection is refused with
    `ERR_MEETING_WINDOW_CONFLICT` (HTTP 409)."

    Design: Corner/validations/corner_meeting_closed_interval_touching_endpoints_conflict
    """
    set_clock("2026-11-03T09:00:00Z")
    event, ticket_type = setup_published_event(
        event_overrides={
            "name": "Touching",
            "starts_at": "2026-11-03T09:00:00Z", "ends_at": "2026-11-03T17:00:00Z",
        }
    )
    r1 = add_registration(event["id"], ticket_type["id"], "t1@example.com")
    r2 = add_registration(event["id"], ticket_type["id"], "t2@example.com")
    r3 = add_registration(event["id"], ticket_type["id"], "t3@example.com")

    first = add_match_request(
        event["id"], r1["id"], r2["id"],
        window_start="2026-11-03T12:00:00Z", window_end="2026-11-03T13:00:00Z",
    )
    accept_match_request(first["id"], r2["id"])

    second = add_match_request(
        event["id"], r3["id"], r2["id"],
        window_start="2026-11-03T13:00:00Z", window_end="2026-11-03T14:00:00Z",
    )

    validate_error(
        api.accept_match_request(second["id"], make_attendee_headers(r2["id"])),
        ApiErrorId.ERR_MEETING_WINDOW_CONFLICT,
    )
    assert read_match_request(first["id"])["state"] == "ACCEPTED"
    assert read_match_request(second["id"])["state"] == "PENDING"
    assert read_registration(r2["id"])["accepted_meeting_count"] == 1, (
        "The refused acceptance must not raise the participant's meeting count"
    )
