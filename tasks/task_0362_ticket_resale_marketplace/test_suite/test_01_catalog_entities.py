"""Catalog entity CRUD, defaults, computed and system fields.

Venue/Section/Event creation, required-field and enum validation, server-minted
defaults and computed fields (PRD §2.4, §2.7, §2.8, §3.1, §3.3).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_seller_headers,
    assert_venue, assert_section, assert_event,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]


def test_create_venue_returns_201_with_system_fields(api):
    """PRD §2.4: "Every persisted resource carries a server-minted `id`, which is a
    UUID with no type prefix ... and `version`, an integer that begins at 1."
    PRD §2.5: "a `Venue` exposes a derived `total_section_count` equal to the
    number of sections under it."

    Design: Corner/entities/create_venue_returns_201_with_system_fields
    """
    venue = validate_success(api.create_venue(F.create_venue_payload(name="Arena"), ADMIN),
                             expected_status=201)
    assert_venue(venue)
    assert venue["version"] == 1
    assert venue["total_section_count"] == 0


def test_get_event_not_found_returns_404(api):
    """PRD §2.7: "The first identifier that fails to resolve produces that
    resource's specific not-found error — `ERR_EVENT_NOT_FOUND`, ..."

    Design: Corner/entities/get_event_not_found_returns_404
    """
    resp = api.get_event(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND.value)


def test_create_listing_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "First, the request body is checked for well-formedness: required
    fields present ... A malformed body is rejected with `ERR_INVALID_REQUEST`
    before any authentication or business logic runs."
    PRD §3.3: "an `ask_price_cents` per seat (greater than zero)".

    Design: Corner/entities/create_listing_missing_required_field_returns_invalid_request
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1, open_for_sale=False)
    seller_h = make_seller_headers(base["seller_id"])
    # Omit ask_price_cents (required input, no default).
    payload = {
        "event_id": base["event_id"],
        "seller_id": base["seller_id"],
        "section_id": base["section_id"],
        "delivery_method": "MOBILE_TRANSFER",
        "pricing_mode": "FIXED",
        "split_rule": "ANY",
    }
    resp = api.create_listing(payload, seller_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_event_price_cap_multiplier_default_applied_when_omitted(api):
    """PRD §3.1: "`price_cap_multiplier`, the maximum listing price expressed as a
    multiple of a section's `face_value_cents` (at least 1.0, defaulting to 3.0),
    and `last_minute_cutoff_minutes`, the number of minutes before `doors_open_at`
    at which last-minute delivery rules engage (at least 0, defaulting to 180)."

    Design: Corner/entities/event_price_cap_multiplier_default_applied_when_omitted
    """
    venue = fx.create_venue()
    # Omit both tuning inputs → defaults apply.
    payload = {"venue_id": venue["id"], "title": "E", "doors_open_at": "2026-09-01T19:00:00.000Z"}
    event = validate_success(api.create_event(payload, ADMIN), expected_status=201)
    assert event["price_cap_multiplier"] == 3.0
    assert event["last_minute_cutoff_minutes"] == 180


def test_seat_section_id_is_system_copied_from_listing(api):
    """PRD §3.3: "The `section_id` on the seat is copied from the parent listing
    rather than supplied. ... A new seat enters in `AVAILABLE` status."

    Design: Corner/entities/seat_section_id_is_system_copied_input_ignored
    """
    base = fx.setup_catalog(face_value_cents=10000, seats_per_row=1, open_for_sale=False)
    seller_h = make_seller_headers(base["seller_id"])
    listing = fx.create_draft_listing(base["event_id"], base["seller_id"], base["section_id"])
    seat = validate_success(api.create_seat(
        F.create_seat_payload(listing["id"], barcode_token="SC-1"), seller_h),
        expected_status=201)
    assert seat["section_id"] == base["section_id"], "seat section_id copied from listing"
    assert seat["status"] == "AVAILABLE"


def test_create_section_invalid_price_zone_enum_returns_invalid_request(api):
    """PRD §2.8: "First, the request body is checked for well-formedness: required
    fields present, types and enum values valid ... A malformed body is rejected
    with `ERR_INVALID_REQUEST`."
    PRD §3.1: "a `price_zone` of `PREMIUM`, `STANDARD`, or `VALUE`".

    Design: Corner/entities/create_section_invalid_price_zone_enum_returns_invalid_request
    """
    venue = fx.create_venue()
    payload = F.create_section_payload(venue["id"], price_zone="GOLD")
    resp = api.create_section(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_section_capacity_computed_from_rows_times_seats(api):
    """PRD §3.1: "On creation the section's `capacity` is computed as `row_count`
    times `seats_per_row`."

    Design: Corner/entities/section_capacity_computed_from_rows_times_seats
    """
    venue = fx.create_venue()
    section = validate_success(api.create_section(
        F.create_section_payload(venue["id"], row_count=3, seats_per_row=4), ADMIN),
        expected_status=201)
    assert_section(section)
    assert section["capacity"] == 12, f"3*4=12, got {section['capacity']}"
