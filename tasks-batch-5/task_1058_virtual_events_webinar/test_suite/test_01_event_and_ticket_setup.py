"""Standing up an event: creation defaults, reads, ticket types and the
publish/cancel gates that guard the event lifecycle."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_event,
    assert_ticket_type,
    assert_session_speaker,
    create_event_payload,
    create_ticket_type_payload,
    create_registration_payload,
    TEST_USERS,
    reset_clock,
    new_event,
    add_ticket_type,
    add_track,
    add_session,
    add_speaker,
    invite_speaker,
    setup_published_event,
    read_event,
    read_ticket_type,
)

ORG = TEST_USERS["organizer_headers"]


def test_event_creation_returns_declared_defaults(api):
    """PRD 3.1: "The new event lands in `DRAFT`, its `organizer_user_id` is
    stamped with the acting `X-User-ID`, and its `version` begins at 1. Its
    counters all begin at zero: `registered_count`, `gross_collected_cents`,
    `streamed_minutes_total`, `published_recording_count` and
    `settlement_adjustment_cents`."

    Design: Corner/entities/corner_event_creation_returns_declared_defaults
    """
    reset_clock()
    payload = create_event_payload(
        name="Corner Event",
        starts_at="2026-10-01T09:00:00Z",
        ends_at="2026-10-01T17:00:00Z",
        early_bird_ends_at="2026-09-01T00:00:00Z",
        capacity=25,
    )
    data = validate_success(api.create_event(payload, ORG), 201)
    assert_event(data)
    assert data["state"] == "DRAFT", f"Expected DRAFT on creation, got {data['state']}"
    assert data["version"] == 1, f"Expected version 1 on creation, got {data['version']}"
    assert data["registered_count"] == 0
    assert data["gross_collected_cents"] == 0
    assert data["streamed_minutes_total"] == 0
    assert data["published_recording_count"] == 0
    assert data["settlement_adjustment_cents"] == 0


def test_event_read_returns_stored_values(api):
    """PRD 3.1: "An `Organizer` opens the workflow by creating an event,
    supplying its public `name`, an IANA `timezone` label, the window bounded by
    `starts_at` and `ends_at`, the instant `early_bird_ends_at` at which
    promotional pricing stops applying, and a `capacity` of at least one."
    PRD 3.1: "Reading a single event returns the `version` a client needs for
    the settlement concurrency check along with every computed counter, and that
    read is open to all six roles."

    Design: Corner/entities/corner_event_read_returns_stored_values
    """
    event = new_event(
        name="Read Me",
        timezone="UTC",
        starts_at="2026-10-02T09:00:00Z",
        ends_at="2026-10-02T17:00:00Z",
        early_bird_ends_at="2026-09-01T00:00:00Z",
        capacity=25,
    )
    data = validate_success(api.get_event(event["id"], ORG), 200)
    assert_event(data)
    assert data["name"] == "Read Me", f"Expected name 'Read Me', got {data['name']}"
    assert data["timezone"] == "UTC"
    assert data["capacity"] == 25, f"Expected capacity 25, got {data['capacity']}"


def test_registrations_list_returns_pagination_envelope(api):
    """PRD 2.3: "The `meta` block of a list response carries `limit` and `offset`
    echoing the effective values used, `total_count` giving the number of rows
    matching the filters before pagination is applied, and `has_more` indicating
    whether any matching rows remain beyond the current page."

    Design: Corner/entities/corner_registrations_list_returns_pagination_envelope
    """
    from test_helpers import add_registration

    event, ticket_type = setup_published_event(
        event_overrides={"name": "Page Me"}, ticket_overrides={"quota": 10}
    )
    add_registration(event["id"], ticket_type["id"], "p1@example.com")
    add_registration(event["id"], ticket_type["id"], "p2@example.com")

    response = api.list_registrations(
        ORG, params={"event_id": event["id"], "limit": 1, "offset": 0}
    )
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == 2, (
        f"Expected total_count 2 before pagination, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, "Expected has_more true with 2 rows and limit 1"
    assert len(rows) == 1, f"Expected exactly 1 row on the page, got {len(rows)}"
    assert meta["limit"] == 1 and meta["offset"] == 0


def test_event_not_found_returns_404(api):
    """PRD 2.6: "A request against a ticket type nested under an event resolves
    the event first; if no event bears that identifier the request fails with
    `ERR_EVENT_NOT_FOUND` (HTTP 404) and the ticket type is never looked up."

    Design: Corner/entities/corner_event_not_found_returns_404
    """
    reset_clock()
    validate_error(
        api.get_event(NON_EXISTENT_UUID, ORG), ApiErrorId.ERR_EVENT_NOT_FOUND
    )


def test_registration_missing_required_field_returns_validation_error(api):
    """PRD 2.7: "Body shape — required fields present, types correct, enum values
    inside their declared sets, integers respecting their minimums, and `limit`
    within 1 to 100 (`ERR_VALIDATION`)."
    PRD 3.3: "A registration is created by an `Organizer` on behalf of an
    attendee, naming the `event_id` and `ticket_type_id`, the `attendee_email`,
    and optionally a `group_code` shared with co-registering colleagues, a
    claimed `group_size` of at least one (defaulting to 1), and a
    `waitlist_if_full` flag."

    Design: Corner/entities/corner_registration_missing_required_field_returns_validation_error
    """
    event, ticket_type = setup_published_event(event_overrides={"name": "Missing Field"})

    validate_error(
        api.create_registration(
            {"event_id": event["id"], "ticket_type_id": ticket_type["id"]}, ORG
        ),
        ApiErrorId.ERR_VALIDATION,
    )
    assert read_ticket_type(ticket_type["id"])["sold_count"] == 0, (
        "A rejected registration must not consume a seat"
    )


def test_ticket_type_computed_counters_ignore_client_input(api):
    """PRD 3.2: "A new ticket type starts with `sold_count` at zero and
    `availability_status` at `AVAILABLE`, and creating one advances the owning
    event's `version`."
    PRD 2.4: "The `updated_at` timestamp records the instant of the most recent
    mutation to the row, and `version` is an integer that starts at 1 when the
    row is created and increases by one on every mutation of that row."

    Design: Corner/entities/corner_ticket_type_computed_counters_ignore_client_input
    """
    event = new_event(name="Computed")
    payload = create_ticket_type_payload(quota=4, gating_level="ON_DEMAND")
    data = validate_success(api.create_ticket_type(event["id"], payload, ORG), 201)
    assert_ticket_type(data)
    assert data["sold_count"] == 0, f"Expected sold_count 0, got {data['sold_count']}"
    assert data["availability_status"] == "AVAILABLE"
    assert data["version"] == 1, f"Expected version 1 on creation, got {data['version']}"


def test_ticket_type_invalid_tier_enum_rejected(api):
    """PRD 3.2: "Under each event the organizer defines one or more ticket types,
    each with a `name`, a `tier` drawn from `GENERAL`, `VIP`, `SPONSOR` and
    `SPEAKER`, a `price_cents` list price of zero or more, a `quota` of at least
    one seat, and a `gating_level` of `LIVE_ONLY`, `ON_DEMAND` or `BOTH`
    describing which consumption channels a holder unlocks."
    PRD 2.7: "Body shape — required fields present, types correct, enum values
    inside their declared sets, integers respecting their minimums, and `limit`
    within 1 to 100 (`ERR_VALIDATION`)."

    Design: Corner/entities/corner_ticket_type_invalid_tier_enum_rejected
    """
    event = new_event(name="Enum Guard")
    payload = create_ticket_type_payload(name="Platinum", tier="PLATINUM", quota=4)
    validate_error(
        api.create_ticket_type(event["id"], payload, ORG), ApiErrorId.ERR_VALIDATION
    )


def test_session_speaker_junction_discoverable_from_speaker_side(api):
    """PRD 3.6: "The junction between a session and a speaker is a first-class
    row carrying `session_id`, `speaker_id`, a `speaking_role` of `HOST`,
    `PANELIST` or `MODERATOR`, its own `state`, and an `invite_round` counter."
    PRD 3.6: "An organizer creates one by inviting a speaker; the row lands in
    `INVITED` with `invite_round` at 1."
    PRD 3.6: "Junction rows are listable with filters on `session_id`,
    `speaker_id` and `state`."

    Design: Corner/entities/corner_session_speaker_junction_discoverable_from_speaker_side
    """
    event = new_event(name="Graph")
    track = add_track(event["id"])
    session = add_session(
        event["id"], track["id"], title="Panel",
        starts_at="2026-10-08T10:00:00Z", ends_at="2026-10-08T11:00:00Z",
    )
    speaker = add_speaker(event["id"], full_name="Ada Poole", email="ada@example.com")
    junction = invite_speaker(session["id"], speaker["id"], speaking_role="MODERATOR")

    rows, meta = validate_paginated(
        api.list_session_speakers(ORG, params={"speaker_id": speaker["id"]})
    )
    assert meta["total_count"] == 1, (
        f"Expected exactly one junction row for the speaker, got {meta['total_count']}"
    )
    assert rows[0]["id"] == junction["id"]
    assert_session_speaker(rows[0])
    assert rows[0]["state"] == "INVITED"
    assert rows[0]["invite_round"] == 1
    assert rows[0]["session_id"] == session["id"]
    assert rows[0]["speaker_id"] == speaker["id"]


def test_publish_without_ticket_type_returns_invalid_state(api):
    """PRD 3.1: "Publishing is permitted only from `DRAFT`, only by the owning
    organizer, and only when the event already has at least one ticket type
    defined — an event with no tickets has nothing to sell, and the attempt is
    refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_publish_without_ticket_type_returns_invalid_state
    """
    event = new_event(name="No Tickets")
    validate_error(
        api.publish_event(event["id"], ORG), ApiErrorId.ERR_INVALID_STATE
    )
    assert read_event(event["id"])["state"] == "DRAFT", (
        "A refused publish must leave the event in DRAFT"
    )


def test_cancel_event_twice_is_refused_and_writes_nothing(api):
    """PRD 3.1: "The event's lifecycle runs `DRAFT → PUBLISHED → LIVE → ENDED →
    SETTLED`, with `CANCELLED` reachable from the first three. `SETTLED` and
    `CANCELLED` are both terminal."
    PRD 2.7: "Declared-transition check (`ERR_INVALID_STATE`), then terminal-state
    check (`ERR_ALREADY_TERMINAL`), on every state-transition endpoint."

    The PRD names both codes for this rung without committing to which one a
    terminal row reports, so either is accepted; the state and version
    assertions are the pinned part.

    Design: Corner/state_machines/corner_cancel_event_twice_returns_already_terminal
    """
    event = new_event(name="Twice Cancelled")
    cancelled = validate_success(api.cancel_event(event["id"], "budget cut", ORG), 200)
    version_after_first = cancelled["version"]

    validate_error_is_one_of(
        api.cancel_event(event["id"], "budget cut again", ORG),
        [ApiErrorId.ERR_ALREADY_TERMINAL.value, ApiErrorId.ERR_INVALID_STATE.value],
    )
    refreshed = read_event(event["id"])
    assert refreshed["state"] == "CANCELLED"
    assert refreshed["version"] == version_after_first, (
        "A refused cancel must not mutate the event, so version must not advance"
    )


def test_registration_counters_visible_in_same_response(api):
    """PRD 3.3: "A seat-holding registration, by contrast, increments both
    counters, triggers the availability recomputation, and has its
    `amount_due_cents` written by the provisional pricing pass."
    PRD 3.2: "The boundary is exact: the seat that takes `sold_count` up to
    `quota` succeeds and flips the type to `SOLD_OUT`, and the next seat request
    is the one that is refused."
    PRD 2.11: "Both chains are described in full where their originating
    operations are specified, and both run to completion within the single
    request that triggers them — this platform has no deferred or
    eventually-consistent propagation."

    Design: Corner/consistency_model/corner_registration_counters_visible_in_same_response
    """
    from test_helpers import add_registration

    event, ticket_type = setup_published_event(
        event_overrides={"name": "Immediate"}, ticket_overrides={"quota": 1}
    )
    add_registration(event["id"], ticket_type["id"], "now@example.com")

    data = validate_success(api.get_ticket_type(ticket_type["id"], ORG), 200)
    assert data["sold_count"] == 1, f"Expected sold_count 1, got {data['sold_count']}"
    assert data["availability_status"] == "SOLD_OUT", (
        f"Expected SOLD_OUT at quota 1, got {data['availability_status']}"
    )
    assert read_event(event["id"])["registered_count"] == 1
