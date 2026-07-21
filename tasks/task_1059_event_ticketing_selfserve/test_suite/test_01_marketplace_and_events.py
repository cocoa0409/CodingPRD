"""Provisioning the marketplace and bringing an event to market."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, ANONYMOUS_HEADERS, TEST_USERS,
    assert_event, assert_organizer, assert_three_fractional_digits,
    create_event_payload,
    setup_marketplace, create_event, create_organizer, create_venue,
    make_organizer_headers, read_event,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Venue occupancy and the ninety-minute turnaround buffer
# ---------------------------------------------------------------------------

def test_event_inside_the_venue_turnaround_buffer_is_double_booked():
    """PRD §3.2: "Concretely, the new event claims the half-open interval that
    begins at its `starts_at` and ends ninety minutes after its `ends_at`; if that
    interval intersects the identically-constructed interval of any other event on
    the same `venue_id` whose status is anything other than `CANCELLED`, the create
    is rejected with `ERR_VENUE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/venue_occupancy_uses_turnaround_buffer_half_open_interval
    """
    ctx = setup_marketplace(venue_overrides={"name": "Turnaround Hall",
                                             "city": "Kansas City",
                                             "seated_capacity": 800})
    create_event(ctx["organizer"], ctx["venue"], title="Early Show",
                 starts_at="2026-08-01T18:00:00Z", ends_at="2026-08-01T22:00:00Z")

    # The first show occupies [18:00, 00:00) once the 90-minute buffer is added,
    # so a 23:00 start lands inside it.
    resp = api_client.create_event(
        create_event_payload(ctx["org_id"], ctx["venue_id"], title="Late Show Too Early",
                             starts_at="2026-08-01T23:00:00Z",
                             ends_at="2026-08-02T01:00:00Z"),
        ctx["org_headers"])
    validate_error(resp, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED.value, 409)

    listed, meta = validate_paginated(
        api_client.list_events(ANONYMOUS_HEADERS, params={"venue_id": ctx["venue_id"]}))
    assert meta["total_count"] == 1, \
        f"Expected the rejected event to be absent, got total_count {meta['total_count']}"


def test_event_starting_exactly_at_the_buffer_edge_is_accepted():
    """PRD §3.2: "Because both intervals are half-open at their upper end, a new
    event whose `starts_at` falls exactly ninety minutes after an existing event's
    `ends_at` is accepted — the boundary instant belongs to the newcomer."

    Design: Difficulty/resource_temporal_overlap/venue_occupancy_uses_turnaround_buffer_half_open_interval
    """
    ctx = setup_marketplace(venue_overrides={"name": "Turnaround Hall",
                                             "city": "Kansas City",
                                             "seated_capacity": 800})
    create_event(ctx["organizer"], ctx["venue"], title="Early Show",
                 starts_at="2026-08-01T18:00:00Z", ends_at="2026-08-01T22:00:00Z")

    resp = api_client.create_event(
        create_event_payload(ctx["org_id"], ctx["venue_id"],
                             title="Late Show On Buffer Edge",
                             starts_at="2026-08-02T00:00:00Z",
                             ends_at="2026-08-02T02:00:00Z"),
        ctx["org_headers"])
    created = validate_success(resp, 201)
    assert_event(created)
    assert created["starts_at"].startswith("2026-08-02T00:00:00"), \
        f"Expected the boundary start instant to be preserved, got {created['starts_at']}"

    listed, meta = validate_paginated(
        api_client.list_events(ANONYMOUS_HEADERS, params={"venue_id": ctx["venue_id"]}))
    assert meta["total_count"] == 2, \
        f"Expected both shows on the venue, got total_count {meta['total_count']}"


# ---------------------------------------------------------------------------
# Creating and reading events
# ---------------------------------------------------------------------------

def test_create_event_returns_draft_with_version_one():
    """PRD §3.2: "The event is created in `DRAFT` status with `version` 1, and its
    four reporting roll-ups `gross_cents`, `refunds_cents`, `issued_count` and
    `checked_in_count` all start at zero."

    Design: Corner/entities/corner_create_event_returns_draft_with_version_one
    """
    ctx = setup_marketplace(venue_overrides={"name": "Corner Hall", "city": "Reno",
                                             "seated_capacity": 120})
    resp = api_client.create_event(
        create_event_payload(ctx["org_id"], ctx["venue_id"], title="Corner Night",
                             starts_at="2026-09-10T18:00:00Z",
                             ends_at="2026-09-10T22:00:00Z"),
        ctx["org_headers"])
    event = validate_success(resp, 201)
    assert_event(event)
    assert event["status"] == "DRAFT", f"Expected DRAFT, got {event['status']}"
    assert event["version"] == 1, f"Expected version 1, got {event['version']}"
    assert event["gross_cents"] == 0
    assert event["refunds_cents"] == 0
    assert event["issued_count"] == 0
    assert event["checked_in_count"] == 0
    assert event["title"] == "Corner Night"


def test_get_event_by_id_returns_the_stored_declarations():
    """PRD §3.2: "`fee_mode` decides who bears the platform fee and takes either
    `PASS_ON` — the default when omitted — or `ABSORB`. `refund_policy` decides the
    default refund variant for the event and takes either `FEE_RETAINED` — the
    default when omitted — or `FEE_INCLUDED`."

    Design: Corner/entities/corner_get_event_by_id_returns_stored_row
    """
    ctx = setup_marketplace(venue_overrides={"name": "Readback Hall", "city": "Boise",
                                             "seated_capacity": 90})
    created = create_event(ctx["organizer"], ctx["venue"], title="Readback Night",
                           starts_at="2026-09-11T18:00:00Z",
                           ends_at="2026-09-11T22:00:00Z",
                           fee_mode="ABSORB", refund_policy="FEE_INCLUDED")

    event = validate_success(api_client.get_event(created["id"], ANONYMOUS_HEADERS), 200)
    assert_event(event)
    assert event["fee_mode"] == "ABSORB", f"Expected ABSORB, got {event['fee_mode']}"
    assert event["refund_policy"] == "FEE_INCLUDED", \
        f"Expected FEE_INCLUDED, got {event['refund_policy']}"
    assert event["venue_id"] == ctx["venue_id"]


def test_get_unknown_event_returns_event_not_found():
    """PRD §3.2: "An event named in a path or body that does not resolve yields
    `ERR_EVENT_NOT_FOUND`."

    Design: Corner/entities/corner_get_event_not_found_returns_event_not_found
    """
    create_organizer(display_name="Void Co", contact_email="ops@void.example")

    resp = api_client.get_event(NON_EXISTENT_UUID, ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error", \
        "Error responses must carry response_type 'error'"


def test_create_event_without_a_title_is_rejected_as_malformed():
    """PRD §3.2: "An organiser opens an event by naming the owning `organizer_id`,
    the `venue_id` it will occupy, a `title`, and the `starts_at` and `ends_at`
    instants that bound it."
    PRD §2.8: "3. **Request shape** — required fields present, types correct, enum
    members drawn from the declared sets, integers inside their declared ranges,
    else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/corner_create_event_missing_required_title_returns_invalid_request
    """
    ctx = setup_marketplace(venue_overrides={"name": "Missing Hall", "city": "Fargo",
                                             "seated_capacity": 60})
    resp = api_client.create_event(
        {"organizer_id": ctx["org_id"], "venue_id": ctx["venue_id"],
         "starts_at": "2026-09-13T18:00:00Z", "ends_at": "2026-09-13T22:00:00Z"},
        ctx["org_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    listed, meta = validate_paginated(
        api_client.list_events(ANONYMOUS_HEADERS, params={"organizer_id": ctx["org_id"]}))
    assert meta["total_count"] == 0, \
        f"A rejected create must persist nothing, got total_count {meta['total_count']}"


def test_new_organizer_opens_with_zeroed_lifetime_counters():
    """PRD §3.1: "Two lifetime money counters are opened at zero on that record and
    never edited directly: `lifetime_gross_cents` accumulates the organiser-credited
    amount of every order that reaches paid status across every event the organiser
    owns, and `lifetime_refunds_cents` accumulates the organiser-charged amount of
    every refund that reaches settlement across the same events."
    PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
    with three fractional digits, recording the instant of creation as read from the
    logical clock."

    Design: Corner/entities/corner_client_supplied_system_fields_on_organizer_input_ignored
    """
    create_venue(name="Ignore Hall", city="Mesa", seated_capacity=50)

    resp = api_client.create_organizer(
        {"display_name": "Ignore Co", "contact_email": "ops@ignore.example"}, ADMIN)
    organizer = validate_success(resp, 201)
    assert_organizer(organizer)
    assert organizer["version"] == 1, \
        f"A newly created resource begins at version 1, got {organizer['version']}"
    assert organizer["lifetime_gross_cents"] == 0
    assert organizer["lifetime_refunds_cents"] == 0
    assert_three_fractional_digits(organizer["created_at"], "organizer.created_at")


def test_request_without_auth_headers_is_unauthenticated():
    """PRD §2.1: "A request whose `X-User-Role` header is missing, or whose value is
    not one of those six strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401);
    the same rejection applies when `X-User-ID` is missing for any role other than
    `Anonymous`, which alone requires no `X-User-ID`."

    Design: Corner/rbac/corner_missing_auth_headers_returns_unauthenticated
    """
    ctx = setup_marketplace(venue_overrides={"name": "Anon Hall", "city": "Tacoma",
                                             "seated_capacity": 60})
    resp = api_client.create_event(
        create_event_payload(ctx["org_id"], ctx["venue_id"], title="Anon Night",
                             starts_at="2026-10-22T18:00:00Z",
                             ends_at="2026-10-22T22:00:00Z"),
        headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    listed, meta = validate_paginated(
        api_client.list_events(ANONYMOUS_HEADERS, params={"organizer_id": ctx["org_id"]}))
    assert meta["total_count"] == 0, \
        f"An unauthenticated create must persist nothing, got {meta['total_count']}"
