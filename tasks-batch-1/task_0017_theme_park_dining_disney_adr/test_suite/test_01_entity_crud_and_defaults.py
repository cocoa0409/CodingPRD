"""Entity creation, retrieval, defaults, required fields, and listing — Queue B (Corner)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_guest_payload,
    create_restaurant_payload,
    create_reservation_payload,
    create_dining_plan_payload,
    create_park_session_payload,
    set_clock,
    setup_guest_restaurant_plan_session,
    create_guest,
    create_restaurant,
    TEST_USERS,
    make_guest_headers,
    ApiErrorId,
)


def test_create_guest_returns_201_with_default_status_active(api):
    """PRD §3.1: "New guests open in ACTIVE status with no_show_strike_count set to 0;
    both fields are system-managed thereafter."
    PRD §2.4: "The version field is an integer that begins at 1 on creation
    and is incremented by exactly 1 on every server-committed mutation"

    Design: Corner/entities/create_guest_returns_201_with_default_status_active
    """
    set_clock("2026-01-15T12:00:00Z")
    payload = create_guest_payload(
        email="corner_guest@x.com",
        full_name="Corner Guest",
        home_timezone="America/New_York",
    )
    res = api.create_guest(payload, TEST_USERS["platform_admin_headers"])
    guest = validate_success(res, expected_status=201)
    assert guest["status"] == "ACTIVE"
    assert guest["no_show_strike_count"] == 0
    assert guest["version"] == 1


def test_get_guest_not_found_returns_404(api):
    """PRD §2.9: "a path id that does not resolve to an existing row yields
    ERR_NOT_FOUND (HTTP 404) before any body or precondition is inspected."

    Design: Corner/entities/get_guest_not_found_returns_404
    """
    set_clock("2026-01-15T12:00:00Z")
    res = api.get_guest("00000000-0000-4000-8000-000000000000", TEST_USERS["platform_admin_headers"])
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_list_restaurants_returns_all_when_under_default_limit(api):
    """PRD §2.3: "All list endpoints accept two query parameters, limit and offset, and
    return the four pagination fields (limit, offset, total_count, has_more) inside the
    meta envelope. The limit parameter defaults to 10 when omitted, has a minimum value
    of 1, and is capped at a maximum of 100; the offset parameter defaults to 0"

    Design: Corner/entities/list_restaurants_pagination_defaults_applied
    """
    set_clock("2026-01-15T12:00:00Z")
    for name in ("R1", "R2", "R3"):
        create_restaurant(name=name, park_code="EPCOT")
    res = api.list_restaurants(TEST_USERS["platform_admin_headers"])
    data, meta = validate_paginated(res)
    assert len(data) == 3
    assert meta["total_count"] == 3


def test_create_reservation_missing_required_party_size_returns_invalid_request(api):
    """PRD §5 + §3.3: party_size is a required input on POST /v1/reservations.
    PRD §5: "ERR_INVALID_REQUEST | 400" is the platform's response for malformed
    request bodies.

    Design: Corner/entities/create_reservation_missing_required_field_returns_invalid_request
    """
    set_clock("2026-01-15T12:00:00Z")
    guest, restaurant, dp, ps = setup_guest_restaurant_plan_session()
    payload = create_reservation_payload(
        guest_id=guest["id"],
        restaurant_id=restaurant["id"],
        park_session_id=ps["id"],
        dining_plan_id=dp["id"],
        slot_start_utc="2026-02-15T18:00:00Z",
    )
    payload.pop("party_size")
    res = api.create_reservation(payload, make_guest_headers(guest["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_dining_plan_held_field_initial_value_is_zero_on_create(api):
    """PRD §3.1: "On creation the plan's table_service_credits_remaining is set
    equal to table_service_credits_initial, table_service_credits_held starts at 0,
    and the plan opens in ACTIVE status."

    Design: Corner/entities/dining_plan_held_field_initial_value_is_zero_on_create
    """
    set_clock("2026-01-15T12:00:00Z")
    guest = create_guest(email="dpc_corner@x.com", full_name="DPC")
    payload = create_dining_plan_payload(
        guest_id=guest["id"],
        tier="DELUXE",
        table_service_credits_initial=25,
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2026-12-31T00:00:00Z",
    )
    res = api.create_dining_plan(payload, TEST_USERS["platform_admin_headers"])
    dp = validate_success(res, expected_status=201)
    assert dp["table_service_credits_remaining"] == 25
    assert dp["table_service_credits_held"] == 0
    assert dp["status"] == "ACTIVE"
