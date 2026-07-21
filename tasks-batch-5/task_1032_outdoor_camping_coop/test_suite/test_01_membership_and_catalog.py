"""Membership registration, catalog validation, and filtered-list reads.

Queue-B (corner) coverage for the entities and endpoints sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, ApiErrorId,
    create_member_payload, create_gear_sku_payload, create_gear_unit_payload,
    create_class_trip_payload,
    assert_member, assert_class_trip,
    new_gear_sku, new_gear_unit,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
PUBLIC = TEST_USERS["public_headers"]


def test_member_creation_returns_201_with_defaults(api):
    """PRD §3.1: "membership_tier is either BASIC or PREMIER and defaults to BASIC,
    where a PREMIER member earns a ten percent purchase discount that surfaces in
    rental and order pricing; membership_status is either ACTIVE or LAPSED and
    defaults to ACTIVE."
    PRD §3.1: "A new member's store_credit_cents, loyalty_points_balance, and
    lifetime_eligible_spend_cents all begin at zero."

    Design: Corner/entities/member_creation_returns_201_with_defaults
    """
    res = api.create_member(create_member_payload(email="e1@x.com", full_name="Ent One"), PUBLIC)
    member = validate_success(res, 201)
    assert_member(member)
    assert member["membership_tier"] == "BASIC"
    assert member["membership_status"] == "ACTIVE"
    assert member["store_credit_cents"] == 0
    assert member["loyalty_points_balance"] == 0
    assert member["lifetime_eligible_spend_cents"] == 0


def test_member_get_nonexistent_returns_not_found(api):
    """PRD §2.8: "the system validates existence left to right, in the order the
    identifiers are encountered ... and rejects on the first identifier that does
    not resolve, returning the specific not-found error for that resource type
    (ERR_MEMBER_NOT_FOUND, ...), each carrying HTTP 404."

    Design: Corner/entities/member_get_nonexistent_returns_not_found
    """
    res = api.get_member(NON_EXISTENT_UUID, STAFF)
    validate_error(res, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


def test_gear_sku_missing_required_field_returns_validation(api):
    """PRD §2.8: "Malformed bodies, missing required fields, bad enum values, and
    non-positive values where a positive number is required are rejected with
    ERR_VALIDATION (HTTP 400)."
    PRD §3.1: "A gear SKU is created with a name, a category drawn from TENT,
    BACKPACK, KAYAK, STOVE, or APPAREL, and a retail_price_cents that must be zero
    or greater."

    Design: Corner/entities/gear_sku_missing_required_field_returns_validation
    """
    payload = {"name": "No Price", "category": "TENT"}  # retail_price_cents omitted
    res = api.create_gear_sku(payload, STAFF)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_gear_sku_invalid_category_enum_returns_validation(api):
    """PRD §2.8: "Malformed bodies, missing required fields, bad enum values, and
    non-positive values where a positive number is required are rejected with
    ERR_VALIDATION (HTTP 400)."

    Design: Corner/entities/gear_sku_invalid_category_enum_returns_validation
    """
    payload = create_gear_sku_payload(name="Bad Cat", category="SPACESUIT", retail_price_cents=1000)
    res = api.create_gear_sku(payload, STAFF)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_classtrip_computed_seats_available_equals_capacity_on_create(api):
    """PRD §3.5: "A trip begins SCHEDULED with seats_reserved at zero,
    seats_available equal to its capacity, and waitlist_count at zero."

    Design: Corner/entities/classtrip_computed_seats_available_equals_capacity_on_create
    """
    payload = create_class_trip_payload(
        title="Ent Trip", category="GUIDED_TRIP",
        start_at="2026-08-05T08:00:00Z", end_at="2026-08-05T16:00:00Z",
        capacity=4, price_cents=5000)
    trip = validate_success(api.create_class_trip(payload, STAFF), 201)
    assert_class_trip(trip)
    assert trip["seats_reserved"] == 0
    assert trip["seats_available"] == 4
    assert trip["waitlist_count"] == 0


def test_gear_unit_bad_sku_reference_returns_not_found(api):
    """PRD §2.8: "the system validates existence left to right ... and rejects on
    the first identifier that does not resolve, returning the specific not-found
    error for that resource type (ERR_MEMBER_NOT_FOUND, ERR_GEAR_SKU_NOT_FOUND,
    ...), each carrying HTTP 404."

    Design: Corner/entities/gear_unit_bad_sku_reference_returns_not_found
    """
    payload = create_gear_unit_payload("11111111-1111-4111-8111-111111111111", serial_number="X-1")
    res = api.create_gear_unit(payload, STAFF)
    validate_error(res, ApiErrorId.ERR_GEAR_SKU_NOT_FOUND.value)


def test_gear_units_filtered_list_by_sku_returns_children(api):
    """PRD §2.8: "cross-collection reverse reachability is provided by filtered list
    endpoints rather than nested URLs: gear units filter by gear_sku_id; rentals by
    member_id and gear_unit_id; ..."

    Design: Corner/endpoints/gear_units_filtered_list_by_sku_returns_children
    """
    sku = new_gear_sku(name="Ep Kayak", category="KAYAK", price_cents=70000,
                       rentable=True, daily_rental_rate_cents=2500)
    new_gear_unit(sku["id"], serial="EP-1")
    new_gear_unit(sku["id"], serial="EP-2")

    data, meta = validate_paginated(api.list_gear_units(STAFF, params={"gear_sku_id": sku["id"]}))
    assert len(data) == 2
    for unit in data:
        assert unit["gear_sku_id"] == sku["id"]
