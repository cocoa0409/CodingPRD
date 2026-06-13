"""Entity CRUD, defaults, computed fields, append-only shape, RBAC, and the
remaining error-catalogue corner instances.

Covers the corner entities / endpoints / errors / rbac sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_customer_headers, TEST_USERS, ANONYMOUS_HEADERS,
    create_restaurant_payload, create_dining_area_payload, create_table_payload,
    create_customer_payload, create_special_request_payload,
    create_deposit_hold_payload, create_reservation_payload,
    setup_floor, book_reservation, place_hold, current_table_version,
    make_restaurant, make_dining_area, make_table, make_customer,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]
CUSTOMER = TEST_USERS["customer_headers"]


# ─── entities: creation, retrieval, listing, defaults, computed, types ─────
def test_create_restaurant_returns_201_with_defaults(api):
    """PRD §3.1: "The `per_seat_deposit_cents` is the standard refundable deposit
    charged per seat and defaults to 2500 ... The `deposit_required_party_threshold`
    is the party size at or above which a booking must be backed by a deposit
    before it can be confirmed; it defaults to 6 ... A restaurant is born `OPEN`".

    Design: Corner/entities/create_restaurant_returns_201_with_defaults
    """
    res = validate_success(api.create_restaurant({"name": "Solo"}, MANAGER), 201)
    assert res["status"] == "OPEN"
    assert res["per_seat_deposit_cents"] == 2500
    assert res["deposit_required_party_threshold"] == 6
    assert res["version"] == 1


def test_get_table_returns_stored_entity(api):
    """PRD §3.1: "A table is born `AVAILABLE` (and at `version` 1)".

    Design: Corner/entities/get_table_returns_stored_entity
    """
    restaurant = make_restaurant()
    area = make_dining_area(restaurant["id"])
    table = make_table(area["id"], max_party_size=8)
    got = validate_success(api.get_table(table["id"], HOST), 200)
    assert got["status"] == "AVAILABLE"
    assert got["version"] == 1
    assert got["max_party_size"] == 8


def test_list_reservations_paginated_envelope(api):
    """PRD §2.3: "the pagination fields surfaced in the `meta` block of a list
    response are `limit`, `offset`, `total_count`, and `has_more`, where
    `total_count` is the number of records matching the filter before pagination
    and `has_more` indicates whether records beyond the current page remain."

    Design: Corner/entities/list_reservations_paginated_envelope
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                     floor["table"]["id"], party_size=2)
    data, meta = validate_paginated(
        api.list_reservations(HOST, params={"restaurant_id": floor["restaurant"]["id"]}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_get_reservation_nonexistent_returns_not_found(api):
    """PRD §2.8: "the first identifier that does not resolve yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_reservation_nonexistent_returns_not_found
    """
    resp = api.get_reservation("00000000-0000-4000-8000-000000000000", HOST)
    validate_error(resp, "ERR_NOT_FOUND")


def test_create_table_missing_max_party_size_returns_validation(api):
    """PRD §2.10: "Malformed bodies — a missing required field, a bad enum value,
    a phone that does not match the required format ... — are rejected with
    `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_table_missing_required_max_party_size_returns_validation
    """
    restaurant = make_restaurant()
    area = make_dining_area(restaurant["id"])
    resp = api.create_table(
        {"dining_area_id": area["id"], "label": "T1", "min_party_size": 1}, MANAGER)
    validate_error(resp, "ERR_VALIDATION")


def test_create_dining_area_default_kind_standard(api):
    """PRD §3.1: "a `kind` that is either `STANDARD` (hosting ordinary
    reservations) or `PRIVATE` (a room that can be bought out wholesale); `kind`
    defaults to `STANDARD`. An area begins `AVAILABLE`".

    Design: Corner/entities/create_dining_area_default_kind_standard
    """
    restaurant = make_restaurant()
    res = validate_success(api.create_dining_area(
        {"restaurant_id": restaurant["id"], "name": "MAIN"}, MANAGER), 201)
    assert res["kind"] == "STANDARD"
    assert res["status"] == "AVAILABLE"


def test_turn_window_computed_from_restaurant_default(api):
    """PRD §3.3: "The `turn_window_end` is the `reservation_start` plus the
    effective turn time in minutes, and the `release_at` is `turn_window_end`
    plus the restaurant's `cleanup_buffer_minutes`".

    Design: Corner/entities/reservation_turn_window_computed_input_ignored
    """
    floor = setup_floor(restaurant_overrides={"default_turn_time_minutes": 90,
                                              "cleanup_buffer_minutes": 15},
                        table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=2,
                           reservation_start="2026-06-15T18:00:00Z")
    assert res["turn_window_end"] == "2026-06-15T19:30:00.000Z"
    assert res["release_at"] == "2026-06-15T19:45:00.000Z"


def test_per_table_turn_override_applied(api):
    """PRD §3.3: "The **effective turn time** is the table's `turn_time_minutes`
    when that override is present, and otherwise the restaurant's
    `default_turn_time_minutes`."

    Design: Corner/entities/table_per_table_turn_override_applied
    """
    floor = setup_floor(restaurant_overrides={"default_turn_time_minutes": 90,
                                              "cleanup_buffer_minutes": 15},
                        table_overrides={"max_party_size": 8, "turn_time_minutes": 120})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=2,
                           reservation_start="2026-06-15T18:00:00Z")
    # 18:00 + 120 (override) → 20:00; + 15 buffer → 20:15.
    assert res["turn_window_end"] == "2026-06-15T20:00:00.000Z"
    assert res["release_at"] == "2026-06-15T20:15:00.000Z"


def test_customer_system_fields_initialized(api):
    """PRD §3.2: "A new `Customer` is `ACTIVE` with `no_show_strikes` at 0." and
    "It begins at 100.0" (the settled_reliability_pct).

    Design: Corner/entities/customer_system_fields_generated
    """
    res = validate_success(api.create_customer(create_customer_payload()), 201)
    assert res["no_show_strikes"] == 0
    assert res["status"] == "ACTIVE"
    assert res["settled_reliability_pct"] == 100.0


def test_register_customer_bad_phone_format_validation(api):
    """PRD §3.2: "a `phone` in E.164 form (it must match a leading plus sign
    followed by a non-zero digit and then six to fourteen further digits ...) ...
    a malformed `phone` is an `ERR_VALIDATION` failure."

    Design: Corner/entities/register_customer_bad_phone_format_validation
    """
    resp = api.create_customer({"full_name": "Bad", "phone": "5551234"})
    validate_error(resp, "ERR_VALIDATION")


def test_special_request_has_no_version_field(api):
    """PRD §2.4: "Two resource kinds are append-only records and therefore carry
    only `id` and `created_at` — they have **no** `updated_at` and **no**
    `version` field: the `SpecialRequest` and the `Notification`."

    Design: Corner/entities/special_request_immutable_no_version_field
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=2)
    sr = validate_success(api.create_special_request(
        res["id"], {"category": "DIETARY", "note": "nut allergy"},
        make_customer_headers(floor["customer"]["id"])), 201)
    assert sr["acknowledged"] is False
    assert "version" not in sr
    assert "updated_at" not in sr


def test_create_table_wrong_parent_dining_area_not_found(api):
    """PRD §2.8: "the first unresolved reference yields `ERR_NOT_FOUND`."

    Design: Corner/entities/create_table_wrong_parent_dining_area_not_found
    """
    resp = api.create_table(
        {"dining_area_id": "00000000-0000-4000-8000-0000000000aa",
         "label": "T1", "min_party_size": 1, "max_party_size": 8}, MANAGER)
    validate_error(resp, "ERR_NOT_FOUND")


# ─── endpoints: duplicate hold, special-request acknowledge, pagination ────
def test_place_second_deposit_hold_duplicate_rejected(api):
    """PRD §3.4: "A second hold may not be placed on a reservation that already
    carries a hold that is neither `RELEASED` nor `EXPIRED`; that attempt is
    rejected with `ERR_DUPLICATE_DEPOSIT_HOLD`."

    Design: Corner/endpoints/place_second_deposit_hold_duplicate_rejected
    """
    floor = setup_floor(restaurant_overrides={"per_seat_deposit_cents": 2500,
                                              "deposit_required_party_threshold": 6},
                        table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=6)
    place_hold(res["id"], floor["customer"]["id"])
    resp = api.place_deposit_hold(
        res["id"], create_deposit_hold_payload(card_last4="1111"),
        make_customer_headers(floor["customer"]["id"]))
    validate_error(resp, "ERR_DUPLICATE_DEPOSIT_HOLD")


def test_acknowledge_special_request_sets_flag(api):
    """PRD §3.7: "A host may acknowledge a request, which sets `acknowledged`
    true; once acknowledged it is immutable."

    Design: Corner/endpoints/special_request_acknowledge_computed_flag
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=2)
    sr = validate_success(api.create_special_request(
        res["id"], {"category": "OCCASION", "note": "anniversary"},
        make_customer_headers(floor["customer"]["id"])), 201)
    acked = validate_success(api.acknowledge_special_request(sr["id"], HOST), 200)
    assert acked["acknowledged"] is True


def test_pagination_limit_out_of_bounds_rejected(api):
    """PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is
    rejected with `ERR_PAGINATION_INVALID` (HTTP 422)."

    Design: Corner/endpoints/pagination_limit_out_of_bounds_rejected
    """
    restaurant = make_restaurant()
    resp = api.list_reservations(
        HOST, params={"restaurant_id": restaurant["id"], "limit": 500})
    validate_error(resp, "ERR_PAGINATION_INVALID")


# ─── errors: duplicate phone, deposit-required-without-hold ────────────────
def test_duplicate_phone_on_register_rejected(api):
    """PRD §3.2: "A registration whose `phone` duplicates an existing customer's
    is rejected with `ERR_DUPLICATE_PHONE` (HTTP 409)."

    Design: Corner/errors/duplicate_phone_on_register_rejected
    """
    validate_success(api.create_customer(
        {"full_name": "First", "phone": "+15552229999"}), 201)
    resp = api.create_customer({"full_name": "Second", "phone": "+15552229999"})
    validate_error(resp, "ERR_DUPLICATE_PHONE")


def test_confirm_deposit_required_without_hold_rejected(api):
    """PRD §3.4: "A confirm attempted on a deposit-required booking with no held
    deposit is rejected with `ERR_DEPOSIT_REQUIRED` (HTTP 402)".

    Design: Corner/errors/confirm_deposit_required_without_hold_rejected
    """
    floor = setup_floor(restaurant_overrides={"per_seat_deposit_cents": 2500,
                                              "deposit_required_party_threshold": 6},
                        table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=6)
    resp = api.confirm_reservation(res["id"], HOST)
    validate_error(resp, "ERR_DEPOSIT_REQUIRED")
    after = validate_success(api.get_reservation(res["id"], HOST), 200)
    assert after["status"] == "REQUESTED"


# ─── rbac: role-denied and ownership ───────────────────────────────────────
def test_customer_cannot_confirm_reservation(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not
    permitted to perform the requested operation under the authorization rules
    of this document, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4 endpoint table: confirm is authorized for Host only.

    Design: Corner/rbac/customer_cannot_confirm_reservation
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=2)
    resp = api.confirm_reservation(res["id"], make_customer_headers(floor["customer"]["id"]))
    validate_error(resp, "ERR_FORBIDDEN")
    after = validate_success(api.get_reservation(res["id"], HOST), 200)
    assert after["status"] == "REQUESTED"


def test_host_cannot_create_restaurant(api):
    """PRD §2.1: "the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4 endpoint table: POST /restaurants is authorized for Manager only.

    Design: Corner/rbac/host_cannot_create_restaurant
    """
    resp = api.create_restaurant({"name": "Nope"}, HOST)
    validate_error(resp, "ERR_FORBIDDEN")


def test_customer_cannot_cancel_others_reservation(api):
    """PRD §2.1: "A guest acting as a `Customer` may only cancel or reschedule a
    reservation, or cancel a waitlist entry, when that resource's `customer_id`
    equals their `X-User-ID`; an attempt to act on another guest's resource is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_cancel_others_reservation_ownership
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    custA = floor["customer"]["id"]
    custB = make_customer()["id"]
    res = book_reservation(floor["restaurant"]["id"], custA,
                           floor["table"]["id"], party_size=2)
    resp = api.cancel_reservation(res["id"], make_customer_headers(custB))
    validate_error(resp, "ERR_NOT_RESOURCE_OWNER")
    after = validate_success(api.get_reservation(res["id"], HOST), 200)
    assert after["status"] == "REQUESTED"


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "If either header is missing or malformed on an endpoint that
    requires authentication, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/unauthenticated_request_rejected
    """
    resp = api.get_reservation("00000000-0000-4000-8000-000000000000",
                               ANONYMOUS_HEADERS)
    validate_error(resp, "ERR_UNAUTHENTICATED")
