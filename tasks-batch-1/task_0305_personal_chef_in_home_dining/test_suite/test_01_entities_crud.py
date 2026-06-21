"""Entity creation, defaults, computed-field resolution, listing, and not-found.

Queue B / Corner / entities.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_chef, assert_booking,
    create_chef_payload, create_booking_payload,
    admin_headers, make_chef_headers, make_client_headers,
    pin_clock, create_active_chef, create_chef, create_client,
    NONEXISTENT_BOOKING_ID,
)


def test_create_chef_returns_201_with_defaults_and_system_fields(api):
    """PRD §3.1: "A freshly registered chef starts in `DRAFT` status." and
    "a `prep_buffer_minutes` value ... defaulting to 90 ..." and
    "a `max_bookings_per_day` ... defaulting to 2 ...".
    PRD §3.1: "both reliability scores — `settled_reliability_score` and
    `projected_reliability_score` — start at 50."
    PRD §2.4: "The `version` begins at 1 when the resource is created ...".

    Design: Corner/entities/create_chef_returns_201_with_defaults_and_system_fields
    """
    pin_clock()
    res = api.create_chef(create_chef_payload(display_name="Solo Chef", home_base_zip="94101"),
                          admin_headers())
    chef = validate_success(res, 201)
    assert_chef(chef)
    assert chef["status"] == "DRAFT"
    assert chef["prep_buffer_minutes"] == 90
    assert chef["max_bookings_per_day"] == 2
    assert chef["settled_reliability_score"] == 50
    assert chef["projected_reliability_score"] == 50
    assert chef["version"] == 1


def test_create_booking_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "general field-shape validation (`ERR_INVALID_REQUEST`, HTTP 400)
    guards every create and update: required fields present, enum values in range,
    `event_end_utc` strictly after `event_start_utc`, `max_party_size` at least
    `min_party_size`, and `weekday` between 0 and 6 inclusive."
    PRD §3.3: "A client opens a booking by submitting the target `chef_id`, its own
    `client_id`, the chosen `menu_package_id`, the `party_size` ..., the `service_zip`
    ..., and the event window as `event_start_utc` and `event_end_utc` ...".

    Design: Corner/entities/create_booking_missing_required_field_returns_invalid_request
    """
    pin_clock()
    chef = create_chef()
    ch = make_chef_headers(chef["id"])
    menu = validate_success(api.create_menu({
        "chef_id": chef["id"], "title": "M",
        "base_price_per_guest_cents": 9000, "estimated_ingredient_per_guest_cents": 4000,
    }, ch), 201)
    client = create_client()
    payload = create_booking_payload(chef["id"], client["id"], menu["id"])
    del payload["event_start_utc"]
    res = api.create_booking(payload, make_client_headers(client["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_booking_event_end_before_start_returns_invalid_request(api):
    """PRD §2.9: "general field-shape validation (`ERR_INVALID_REQUEST`, HTTP 400)
    guards every create and update: required fields present, enum values in range,
    `event_end_utc` strictly after `event_start_utc`, `max_party_size` at least
    `min_party_size`, and `weekday` between 0 and 6 inclusive."

    Design: Corner/entities/create_booking_event_end_before_start_returns_invalid_request
    """
    pin_clock()
    chef = create_chef()
    ch = make_chef_headers(chef["id"])
    menu = validate_success(api.create_menu({
        "chef_id": chef["id"], "title": "M",
        "base_price_per_guest_cents": 9000, "estimated_ingredient_per_guest_cents": 4000,
    }, ch), 201)
    client = create_client()
    res = api.create_booking(
        create_booking_payload(
            chef["id"], client["id"], menu["id"],
            event_start_utc="2026-08-15T22:00:00Z", event_end_utc="2026-08-15T18:00:00Z",
        ),
        make_client_headers(client["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_get_booking_nonexistent_id_returns_not_found(api):
    """PRD §2.8: "When an endpoint addresses a resource by a path identifier, that
    identifier is validated first; an unknown id yields the appropriate not-found error
    (`ERR_CHEF_NOT_FOUND`, `ERR_MENU_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_RESCHEDULE_NOT_FOUND`, or `ERR_GROCERY_RUN_NOT_FOUND`, all HTTP 404) before
    any state or business rule is evaluated."

    Design: Corner/entities/get_booking_nonexistent_id_returns_not_found
    """
    pin_clock()
    res = api.get_booking(NONEXISTENT_BOOKING_ID, make_client_headers("00000000-0000-4000-8000-0000000000aa"))
    validate_error(res, "ERR_BOOKING_NOT_FOUND", expected_status=404)


def test_booking_computed_quote_fields_zero_before_confirm(api):
    """PRD §3.3: "At creation the system resolves the `travel_zone_id` by prefix-matching
    `service_zip` against the booked chef's zones and copies the matched zone's fee into
    the booking's `travel_fee_cents` ...". PRD §3.3: "The system also derives `event_date`,
    the calendar date (formatted `YYYY-MM-DD` in UTC) taken from `event_start_utc` ...".
    PRD §3.3: "The new booking lands with `lifecycle_status` `REQUESTED` ... No quote is
    computed yet — pricing is frozen at confirmation."

    Design: Corner/entities/booking_computed_quote_fields_zero_before_confirm
    """
    pin_clock()
    chef = create_chef(chef_overrides={"display_name": "Chef CF"})
    ch = make_chef_headers(chef["id"])
    menu = validate_success(api.create_menu({
        "chef_id": chef["id"], "title": "M",
        "base_price_per_guest_cents": 9000, "estimated_ingredient_per_guest_cents": 4000,
    }, ch), 201)
    zone = validate_success(api.create_travel_zone({
        "chef_id": chef["id"], "zone_code": "ZONE_A", "zip_prefixes": ["941"], "travel_fee_cents": 5000,
    }, ch), 201)
    client = create_client()
    booking = validate_success(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], party_size=6, service_zip="94110"),
        make_client_headers(client["id"])), 201)
    assert booking["lifecycle_status"] == "REQUESTED"
    assert booking["quote_total_cents"] == 0
    assert booking["travel_fee_cents"] == 5000
    assert booking["travel_zone_id"] == zone["id"]
    assert booking["event_date"] == "2026-08-15"


def test_create_booking_zip_outside_service_area_returns_error(api):
    """PRD §3.3: "At creation the system resolves the `travel_zone_id` by prefix-matching
    `service_zip` against the booked chef's zones and copies the matched zone's fee into
    the booking's `travel_fee_cents`; if no zone matches, or more than one would, the
    create is rejected with `ERR_ZIP_OUTSIDE_SERVICE_AREA`."

    Design: Corner/entities/create_booking_zip_outside_service_area_returns_error
    """
    pin_clock()
    chef = create_chef()
    ch = make_chef_headers(chef["id"])
    menu = validate_success(api.create_menu({
        "chef_id": chef["id"], "title": "M",
        "base_price_per_guest_cents": 9000, "estimated_ingredient_per_guest_cents": 4000,
    }, ch), 201)
    validate_success(api.create_travel_zone({
        "chef_id": chef["id"], "zone_code": "ZONE_A", "zip_prefixes": ["941"], "travel_fee_cents": 5000,
    }, ch), 201)
    client = create_client()
    res = api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="95000"),
        make_client_headers(client["id"]),
    )
    validate_error(res, "ERR_ZIP_OUTSIDE_SERVICE_AREA", expected_status=422)


def test_list_chefs_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of a list response carries the four pagination fields
    `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of
    records matching the filter before pagination is applied and `has_more` is true when
    records remain beyond the current page."

    Design: Corner/entities/list_chefs_pagination_envelope
    """
    pin_clock()
    api.create_chef(create_chef_payload(display_name="Chef L1", home_base_zip="94101"), admin_headers())
    api.create_chef(create_chef_payload(display_name="Chef L2", home_base_zip="94102"), admin_headers())
    data, meta = validate_paginated(api.list_chefs(admin_headers(), params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
