"""The analytics snapshot and the two access-control gates that sit above every
other check."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_attendee_headers,
    make_unknown_role_headers,
    create_event_payload,
    reset_clock,
    new_event,
    add_ticket_type,
    add_track,
    add_session,
    publish_event,
    start_event,
    add_registration,
    check_in,
    record_watch_minutes,
    read_event,
    setup_published_event,
)

ORG = TEST_USERS["organizer_headers"]


def _summit_l_live_with_one_registered_row():
    """Summit L: one registration that never checks in, so the attendee
    population the snapshot draws from is empty."""
    event, ticket_type = setup_published_event(event_overrides={"name": "Summit L"})
    add_registration(event["id"], ticket_type["id"], "noshow@example.com")
    start_event(event["id"])
    return event, ticket_type


def test_analytics_average_is_zero_for_an_empty_attendee_set(api):
    """PRD 3.10: "It reports `avg_watch_minutes` as the total watch minutes
    divided by the number of unique attendees, carried to two decimal places and
    rounded half up; when the population is empty the average is reported as 0.00
    rather than attempting a division."

    Design: Difficulty/boundary_precision_check/analytics_average_watch_minutes_is_zero_for_empty_attendee_set
    """
    event, ticket_type = _summit_l_live_with_one_registered_row()

    data = validate_success(api.get_event_analytics(event["id"], ORG), 200)
    assert data["unique_attendees"] == 0, (
        f"A REGISTERED row is not an attendee, got {data['unique_attendees']}"
    )
    assert float(data["avg_watch_minutes"]) == 0.00, (
        f"Expected 0.00 rather than a division by zero, got "
        f"{data['avg_watch_minutes']}"
    )
    assert data["total_watch_minutes"] == 0


def test_analytics_still_echoes_the_events_own_counters_when_empty(api):
    """PRD 3.10: "Its attendee population is the set of registrations of the
    event whose `attendance_status` is `CHECKED_IN` or `ATTENDED`; registrations
    in `NO_SHOW`, `WITHDRAWN`, `WAITLISTED` or `REGISTERED` are excluded
    entirely, and only rows created at or before the current logical clock
    participate."
    PRD 3.10: "It reports `on_demand_views` as the sum of `view_count` across the
    event's recordings currently in `PUBLISHED` — retracted and deleted assets
    contribute nothing. Finally it echoes the event's own `registered_count` and
    `gross_collected_cents`."

    Design: Difficulty/boundary_precision_check/analytics_average_watch_minutes_is_zero_for_empty_attendee_set
    """
    event, ticket_type = _summit_l_live_with_one_registered_row()

    data = validate_success(api.get_event_analytics(event["id"], ORG), 200)
    assert data["on_demand_views"] == 0
    assert data["registered_count"] == 1, (
        "The seat-holding row still counts towards registered_count even though it "
        f"is not an attendee; got {data['registered_count']}"
    )
    assert data["gross_collected_cents"] == 0
    assert data["registered_count"] == read_event(event["id"])["registered_count"]


def test_analytics_average_rounds_to_two_decimals(api):
    """PRD 3.10: "From that population the snapshot reports `unique_attendees` as
    the count of rows, and `total_watch_minutes` as the sum of their
    `watched_minutes`."
    PRD 3.10: "It reports `avg_watch_minutes` as the total watch minutes divided
    by the number of unique attendees, carried to two decimal places and rounded
    half up; when the population is empty the average is reported as 0.00 rather
    than attempting a division."

    Design: Corner/calculations/corner_analytics_average_rounds_to_two_decimals
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Averages"})
    track = add_track(event["id"])
    session = add_session(
        event["id"], track["id"], title="Session",
        starts_at="2026-10-25T10:00:00Z", ends_at="2026-10-25T11:00:00Z",
    )
    r1 = add_registration(event["id"], ticket_type["id"], "avg1@example.com")
    r2 = add_registration(event["id"], ticket_type["id"], "avg2@example.com")
    start_event(event["id"])
    check_in(r1["id"])
    check_in(r2["id"])
    record_watch_minutes(session["id"], r1["id"], 10)
    record_watch_minutes(session["id"], r2["id"], 15)

    data = validate_success(api.get_event_analytics(event["id"], ORG), 200)
    assert data["unique_attendees"] == 2
    assert data["total_watch_minutes"] == 25
    assert float(data["avg_watch_minutes"]) == 12.50, (
        f"25 minutes over 2 attendees is 12.50, got {data['avg_watch_minutes']}"
    )


def test_attendee_cannot_publish_event(api):
    """PRD 2.1: "Once the caller is authenticated, the platform checks whether
    the acting role is among those authorised for the specific endpoint being
    called; if it is not, the request is rejected with `ERR_UNAUTHORIZED` (HTTP
    403)."
    PRD 3.1: "Publishing is permitted only from `DRAFT`, only by the owning
    organizer, and only when the event already has at least one ticket type
    defined — an event with no tickets has nothing to sell, and the attempt is
    refused with `ERR_INVALID_STATE`."

    Design: Corner/rbac/corner_attendee_cannot_publish_event
    """
    host_event, host_ticket = setup_published_event(
        event_overrides={"name": "Role Host"}
    )
    registration = add_registration(
        host_event["id"], host_ticket["id"], "role@example.com"
    )

    guarded = new_event(name="Role Guard")
    add_ticket_type(guarded["id"])

    validate_error(
        api.publish_event(guarded["id"], make_attendee_headers(registration["id"])),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    assert read_event(guarded["id"])["state"] == "DRAFT", (
        "A refused publish must leave the event in DRAFT"
    )


def test_undeclared_role_header_returns_unauthenticated(api):
    """PRD 2.1: "Every request to every endpoint must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity
    in which the caller is acting. If either header is absent, or if
    `X-User-Role` is not one of the six role names enumerated below, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before
    anything else the platform does — before the URL is resolved, before the body
    is parsed, before any state is inspected."

    Design: Corner/rbac/corner_missing_role_header_returns_unauthenticated
    """
    reset_clock()
    payload = create_event_payload(
        name="Anon Event",
        starts_at="2026-11-14T09:00:00Z",
        ends_at="2026-11-14T17:00:00Z",
    )
    validate_error(
        api.create_event(payload, make_unknown_role_headers()),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
