"""Resource creation, defaults, computed fields, not-found, and duplicate checks.

Corner coverage over the entities section.
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_venue,
    create_room,
    create_time_slot,
    create_customer,
    create_venue_payload,
    create_room_payload,
    create_customer_payload,
    assert_venue,
    assert_room,
    assert_same_instant,
    make_customer_headers,
    TEST_USERS,
)
from test_helpers.constants import NONEXISTENT_BOOKING_UUID

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["venue_manager_headers"]


def test_create_venue_returns_system_fields_and_policy_defaults(api):
    """PRD §2.4: "`version` is an integer that begins at 1 on creation."
    PRD §3.1: "it ranges from 0.0 to 1.0 and defaults to 0.5."
    PRD §3.1: "it must be at least 1 and defaults to 3."

    POST /venues with only the required fields mints a server id, sets version 1, and
    applies the financial-policy defaults no_show_fee_pct=0.5 and no_show_strike_limit=3.

    Design: Corner/entities/create_venue_returns_201_with_system_fields
    """
    res = api.create_venue(
        create_venue_payload(name="V", timezone="UTC", open_minute_of_day=0, close_minute_of_day=1440),
        ADMIN)
    venue = validate_success(res, 201)
    assert_venue(venue)
    assert venue["version"] == 1
    assert venue["no_show_fee_pct"] == 0.5
    assert venue["no_show_strike_limit"] == 3


def test_create_room_missing_base_price_rejected(api):
    """PRD §2.9: "the system validates the request shape: required body fields must be
    present and well-typed, enum values must be valid, and numeric ranges must hold (for
    instance `group_size` must be an integer and `age` must be at least 0); a violation
    here is `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.1: "Pricing and timing are governed by `base_price_cents` (the per-participant
    price in cents before any rule, at least 0)."

    base_price_cents is a required input with no default; omitting it from a room create
    yields ERR_INVALID_REQUEST (422).

    Design: Corner/entities/create_room_required_field_missing_returns_invalid_request
    """
    venue = create_venue()
    payload = create_room_payload(venue["id"], name="R", min_group_size=1, max_group_size=4,
                                  game_minutes=60)
    del payload["base_price_cents"]
    res = api.create_room(payload, MANAGER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_room_optional_fields_apply_defaults(api):
    """PRD §3.1: "several optional fields: `min_age` (the minimum participant age in whole
    years, at least 0, where 0 means no age floor, defaulting to 0); `waiver_required`
    (defaulting to true, meaning every participant must have a signed waiver before the
    group can be checked in); `private_surcharge_cents` (a flat surcharge added when the
    whole room is reserved privately, at least 0, defaulting to 0); and
    `reset_buffer_minutes` (the reset time after the game during which the room is
    unavailable, at least 0, defaulting to 0)."
    PRD §3.1: "A newly created room starts with `status` of `ACTIVE`."

    Omitting min_age/waiver_required/reset_buffer_minutes applies the PRD defaults
    0/true/0, and the room starts ACTIVE.

    Design: Corner/entities/room_defaults_applied_when_optional_fields_omitted
    """
    venue = create_venue()
    room = validate_success(api.create_room(
        create_room_payload(venue["id"], name="R", min_group_size=1, max_group_size=4,
                            base_price_cents=1000, game_minutes=60), MANAGER), 201)
    assert_room(room)
    assert room["min_age"] == 0
    assert room["waiver_required"] is True
    assert room["reset_buffer_minutes"] == 0
    assert room["status"] == "ACTIVE"


def test_time_slot_computes_game_and_block_end_with_buffer(api):
    """PRD §3.2: "computes two derived instants: `game_end_utc`, which is `start_utc` plus
    the room's `game_minutes`, and `block_end_utc`, which is `start_utc` plus the room's
    `game_minutes` plus the room's `reset_buffer_minutes`."
    PRD §3.2: "A new slot begins with `status` of `OPEN`."

    With game=60 and buffer=30 and start 14:00, game_end_utc is 15:00 and block_end_utc
    is 15:30 (each computed by the server).

    Design: Corner/entities/timeslot_computed_block_end_includes_buffer
    """
    venue = create_venue()
    room = create_room(venue["id"], name="R", min_group_size=1, max_group_size=4,
                       base_price_cents=1000, game_minutes=60, reset_buffer_minutes=30)
    slot = validate_success(api.create_time_slot(
        {"room_id": room["id"], "start_utc": "2026-07-01T14:00:00Z"}, MANAGER), 201)
    assert_same_instant(slot["game_end_utc"], "2026-07-01T15:00:00Z")
    assert_same_instant(slot["block_end_utc"], "2026-07-01T15:30:00Z")
    assert slot["status"] == "OPEN"


def test_get_nonexistent_booking_returns_not_found(api):
    """PRD §2.7: "The first identifier in the chain that does not resolve produces
    `ERR_NOT_FOUND`, and the server does not look further down the chain once a link is
    missing."

    A GET on a well-formed but unminted booking UUID returns ERR_NOT_FOUND (404).

    Design: Corner/entities/get_booking_nonexistent_returns_not_found
    """
    customer = create_customer()
    res = api.get_booking(NONEXISTENT_BOOKING_UUID, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_NOT_FOUND")


def test_duplicate_customer_email_rejected_case_insensitively(api):
    """PRD §3.3: "Customers are registered with an `email` (unique within the system,
    compared case-insensitively) and a `full_name`."
    PRD §3.3: "Registering with an email that already exists is rejected with
    `ERR_DUPLICATE_RESOURCE`."

    Registering a second customer whose email differs only in case from an existing one
    yields ERR_DUPLICATE_RESOURCE (409).

    Design: Corner/entities/duplicate_customer_email_returns_duplicate_resource
    """
    email = "dup.case@example.com"
    validate_success(api.create_customer(create_customer_payload(email=email, full_name="First"), ADMIN), 201)
    res = api.create_customer(create_customer_payload(email=email.upper(), full_name="Second"), ADMIN)
    validate_error(res, "ERR_DUPLICATE_RESOURCE")
