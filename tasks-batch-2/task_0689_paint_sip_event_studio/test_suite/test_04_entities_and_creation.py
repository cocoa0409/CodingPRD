"""Entity creation, defaults, computed fields, immutability, uniqueness, body-FK
resolution, and listing.

Corner queue (B): entities section.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, make_customer_headers, TEST_USERS, ApiErrorId,
    create_studio, create_artist, create_customer,
    setup_open_event_with_customer, book_reservation, event_current_version,
    set_clock, NONEXISTENT_UUID,
)

MANAGER = TEST_USERS["manager_headers"]


def test_create_studio_returns_201_with_system_fields(api):
    """PRD §3.1: "A new studio begins life in ACTIVE status."
    PRD §2.4: "Every such resource exposes an id — a unique, server-minted
    identifier formatted as a UUID, with no type prefix ... The version field is an
    integer that begins at its initial value and increments by one on every
    mutation."

    Design: Corner/entities/create_studio_returns_201_with_system_fields
    """
    resp = api.create_studio({"name": "Room A", "room_capacity_seats": 25}, MANAGER)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["room_capacity_seats"] == 25
    assert data["version"] == 1, f"version begins at 1, got {data['version']}"
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"


def test_create_event_missing_required_field_returns_validation(api):
    """PRD §2.6: "Request-body well-formedness is checked fourth — required fields
    present, enum values valid, integers positive where required, and pagination
    parameters within bounds — yielding ERR_VALIDATION (HTTP 400) on failure."
    PRD §3.2: "It sets price_cents_per_seat (the list price per seat, at least 0)."

    Design: Corner/entities/create_event_missing_required_field_returns_validation
    """
    studio = create_studio(room_capacity_seats=10, name="Room B")
    resp = api.create_event({
        "studio_id": studio["id"], "title": "NoPrice", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 10}, MANAGER)  # price_cents_per_seat omitted
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_get_event_not_found_returns_404(api):
    """PRD §2.5: "When such a path identifier does not correspond to an existing
    resource, the request is rejected with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_event_not_found_returns_404
    """
    resp = api.get_event(NONEXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_event_defaults_applied(api):
    """PRD §3.2: "may set kit_fee_cents ... (at least 0, defaulting to 0). ... The
    byob_allowed flag (default false) ... The min_age field (default 0 ...) ...
    fundraiser_donation_pct ... (it defaults to 0)."
    PRD §3.2: "A StudioManager creates a StudioEvent in DRAFT status."

    Design: Corner/entities/event_default_fields_applied
    """
    studio = create_studio(room_capacity_seats=10, name="Room C")
    resp = api.create_event({
        "studio_id": studio["id"], "title": "Defaults", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER)
    data = validate_success(resp, expected_status=201)
    assert data["kit_fee_cents"] == 0
    assert data["byob_allowed"] is False
    assert data["min_age"] == 0
    assert data["fundraiser_donation_pct"] == 0
    assert data["status"] == "DRAFT"


def test_event_computed_seat_fields_on_fresh_event(api):
    """PRD §2.8: "seats_reserved is the sum of seats over all of the event's
    reservations whose status is HELD, CONFIRMED, or CHECKED_IN. ... seats_available
    is the event's seats_capacity minus seats_reserved minus walk_in_seats, floored
    at zero."

    Design: Corner/entities/event_computed_seat_fields_ignore_input
    """
    studio = create_studio(room_capacity_seats=12, name="Room D")
    resp = api.create_event({
        "studio_id": studio["id"], "title": "Ledger", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 12, "price_cents_per_seat": 4500}, MANAGER)
    data = validate_success(resp, expected_status=201)
    assert data["seats_reserved"] == 0
    assert data["seats_available"] == 12
    assert data["walk_in_seats"] == 0


def test_attendee_is_append_only_no_version(api):
    """PRD §2.4: "The Attendee resource is the sole exception: it carries only id and
    created_at. Attendee records have no updated_at and no version field — neither is
    present in an Attendee's representation."

    Design: Corner/entities/attendee_is_immutable_no_version_field
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=1)
    resp = api.create_attendee({
        "reservation_id": res["id"], "full_name": "A1", "age_years": 30,
        "waiver_signed": True}, make_customer_headers(customer["id"]))
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"])
    assert "created_at" in data
    assert "version" not in data, "Attendee must NOT carry version"
    assert "updated_at" not in data, "Attendee must NOT carry updated_at"


def test_duplicate_customer_email_case_insensitive_conflict(api):
    """PRD §2.7: "A Customer registers with an email, and email comparison is
    case-insensitive: registering an email that collides with an existing customer's
    email (ignoring letter case) is rejected with ERR_DUPLICATE_RESOURCE (HTTP 409)."

    Design: Corner/entities/duplicate_customer_email_returns_conflict
    """
    create_customer(email="dup@x.com", full_name="First")
    resp = api.create_customer({
        "email": "DUP@x.com", "full_name": "Second", "birthdate": "1991-01-01T00:00:00Z"},
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_reservation_bad_customer_reference_not_found(api):
    """PRD §2.5: "When a body names a foreign entity — a studio_id, event_id,
    customer_id, artist_id, reservation_id, or any of the supplied gift-card
    identifiers — and that entity does not exist, the request is rejected with
    ERR_REFERENCE_NOT_FOUND (HTTP 422)."

    Design: Corner/entities/reservation_reference_not_found_bad_customer
    """
    set_clock("2026-04-01T00:00:00Z")
    event, _customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    ver = event_current_version(event["id"])
    resp = api.create_reservation({
        "event_id": event["id"], "customer_id": "00000000-0000-4000-8000-000000000abc",
        "booking_mode": "PUBLIC", "seats": 1, "expected_event_version": ver}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_list_events_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."
    PRD §2.2: "The response_type is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/entities/list_events_paginated_envelope
    """
    studio = create_studio(room_capacity_seats=10, name="Room G")
    get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "E1", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))
    get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "E2", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T13:00:00Z", "end_utc": "2026-04-05T15:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))

    resp = api.list_events(MANAGER, params={"studio_id": studio["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"two events in the studio, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1, f"limit=1 returns one item, got {len(data)}"
