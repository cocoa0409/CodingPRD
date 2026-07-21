"""Rental cross-entity state dependency (pickup needs the unit AVAILABLE), the
buffered unit-overlap temporal rule, and the rentability referential check.

Queue-A depth: cross_entity_state_dependency (rental->unit), resource_temporal_overlap
(unit buffer). Queue-B: unit-not-rentable validation.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_member, new_rentable_unit, new_gear_sku, new_gear_unit,
    quote_rental, pickup, create_rental_payload, make_member_headers,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ─── cross_entity_state_dependency / rental_pickup_requires_unit_available ─

def _two_rentals_one_unit():
    member = new_member()
    _sku, unit = new_rentable_unit(daily_rental_rate_cents=1500, category="TENT",
                                   price_cents=20000)
    r1 = quote_rental(member, unit["id"], "2026-07-05T09:00:00Z", "2026-07-06T09:00:00Z")
    r2 = quote_rental(member, unit["id"], "2026-07-20T09:00:00Z", "2026-07-21T09:00:00Z")
    return member, unit, r1, r2


def test_pickup_second_rental_on_rented_unit_rejected(api):
    """PRD §3.2: "It is allowed only when the rental is QUOTED, when the member's
    membership_status is still ACTIVE, and when the reserved unit is currently
    AVAILABLE; if the unit is already out on another rental the pickup is rejected
    with ERR_UNIT_NOT_READY."

    Design: Difficulty/cross_entity_state_dependency/rental_pickup_requires_unit_available
    """
    _member, _unit, r1, r2 = _two_rentals_one_unit()
    pickup(r1["id"])
    res = api.pickup_rental(r2["id"], STAFF)
    validate_error(res, ApiErrorId.ERR_UNIT_NOT_READY.value)


def test_unit_rented_out_blocks_pickup(api):
    """PRD §3.2: "Pickup advances the rental from QUOTED to PICKED_UP and flips the
    unit from AVAILABLE to RENTED_OUT."
    PRD §3.2: "if the unit is already out on another rental the pickup is rejected
    with ERR_UNIT_NOT_READY."

    Design: Difficulty/cross_entity_state_dependency/rental_pickup_requires_unit_available
    """
    _member, unit, r1, r2 = _two_rentals_one_unit()
    pickup(r1["id"])
    unit_after = validate_success(api.get_gear_unit(unit["id"], STAFF), 200)
    assert unit_after["status"] == "RENTED_OUT"
    res = api.pickup_rental(r2["id"], STAFF)
    validate_error(res, ApiErrorId.ERR_UNIT_NOT_READY.value)


# ─── resource_temporal_overlap / rental_unit_overlap_within_service_buffer ─

def _unit_with_quoted_r1():
    member = new_member()
    _sku, unit = new_rentable_unit(daily_rental_rate_cents=4000, category="KAYAK",
                                   price_cents=120000)
    quote_rental(member, unit["id"], "2026-07-05T09:00:00Z", "2026-07-06T09:00:00Z")
    return member, unit


def test_rental_overlap_within_service_buffer_rejected(api):
    """PRD §3.2: "each rental occupies the half-open interval that runs from its
    start_at up to but not including its due_at extended by a twenty-four-hour
    service buffer, and if the requested interval and an existing interval share any
    instant the quote is rejected with ERR_UNIT_UNAVAILABLE."

    R1 occupies [07-05T09:00, 07-07T09:00); a request starting 07-06T20:00 falls
    inside the buffer.

    Design: Difficulty/resource_temporal_overlap/rental_unit_overlap_within_service_buffer
    """
    member, unit = _unit_with_quoted_r1()
    payload = create_rental_payload(member["id"], unit["id"],
                                    "2026-07-06T20:00:00Z", "2026-07-08T09:00:00Z")
    res = api.create_rental(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_UNIT_UNAVAILABLE.value)


def test_rental_start_inside_buffer_rejected(api):
    """PRD §3.2: "each rental occupies the half-open interval that runs from its
    start_at up to but not including its due_at extended by a twenty-four-hour
    service buffer, and if the requested interval and an existing interval share any
    instant the quote is rejected with ERR_UNIT_UNAVAILABLE."

    A request starting 07-07T08:00 is still before the buffer end 07-07T09:00 and
    therefore overlaps.

    Design: Difficulty/resource_temporal_overlap/rental_unit_overlap_within_service_buffer
    """
    member, unit = _unit_with_quoted_r1()
    payload = create_rental_payload(member["id"], unit["id"],
                                    "2026-07-07T08:00:00Z", "2026-07-09T09:00:00Z")
    res = api.create_rental(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_UNIT_UNAVAILABLE.value)


# ─── Queue-B validations / rental_rejected_when_unit_not_rentable ──────────

def test_rental_rejected_when_unit_not_rentable(api):
    """PRD §3.2: "The referenced unit's parent SKU must be rentable; a quote against
    a non-rentable SKU is rejected with ERR_UNIT_NOT_RENTABLE."

    Design: Corner/validations/rental_rejected_when_unit_not_rentable
    """
    member = new_member()
    sku = new_gear_sku(name="Display Only", category="TENT", price_cents=30000, rentable=False)
    unit = new_gear_unit(sku["id"], serial="VA-2")
    payload = create_rental_payload(member["id"], unit["id"],
                                    "2026-07-05T09:00:00Z", "2026-07-06T09:00:00Z")
    res = api.create_rental(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_UNIT_NOT_RENTABLE.value)
