"""Gear rental: fee calculation, turnaround windows, unit-state gating, conservation, damage cascade."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures, factories,
)

ADMIN = fixtures.ADMIN
STAFF = fixtures.STAFF


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / rental_fee_peak_tier_cap_mode_a
# ---------------------------------------------------------------------------

def test_reservation_rental_days_rounded_up(api):
    """PRD §3.3: "The reservation's `rental_days` is the number of whole days
    between `start_date` and `end_date`, rounded up, with a minimum of 1."

    Design: Difficulty/combinatorial_formula/rental_fee_peak_tier_cap_mode_a
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit = fixtures.setup_reservation_with_unit(
        api, tier="PREMIER", base_daily_rate_cents=5000, replacement_value_cents=300000)
    res = validate_success(api.create_reservation(factories.reservation_payload(
        member["id"], unit["id"], "2026-07-10T00:00:00Z", "2026-07-14T00:00:00Z"),
        member_headers), 201)
    assert res["rental_days"] == 4


def test_rental_fee_peak_tier_discount_and_cap(api):
    """PRD §3.3: "Start from the raw fee: the product's `base_daily_rate_cents`
    multiplied by `rental_days`. If the reservation's `start_date` falls in peak
    season ... the raw fee is multiplied by the peak multiplier of 1.25 and
    rounded half-up to a whole cent ... a `PREMIER` member's is 0.10, so the
    peak-adjusted amount is multiplied by one minus that discount and rounded
    half-up to a whole cent. Finally the result is capped at the product's
    `replacement_value_cents`: the pinned `rental_fee_cents` is the smaller of
    the discounted amount and the replacement value."

    Design: Difficulty/combinatorial_formula/rental_fee_peak_tier_cap_mode_a
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit = fixtures.setup_reservation_with_unit(
        api, tier="PREMIER", base_daily_rate_cents=5000, replacement_value_cents=300000)
    res = validate_success(api.create_reservation(factories.reservation_payload(
        member["id"], unit["id"], "2026-07-10T00:00:00Z", "2026-07-14T00:00:00Z"),
        member_headers), 201)
    assert res["rental_fee_cents"] == 22500


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / rental_window_buffer_overlap_halfopen
# ---------------------------------------------------------------------------

def _unit_with_first_reservation(api):
    member, member_headers, product, unit = fixtures.setup_reservation_with_unit(
        api, base_daily_rate_cents=3000, replacement_value_cents=100000)
    validate_success(api.create_reservation(factories.reservation_payload(
        member["id"], unit["id"], "2026-08-01T00:00:00Z", "2026-08-05T00:00:00Z"),
        member_headers), 201)
    return member, member_headers, unit


def test_reservation_within_turnaround_buffer_rejected(api):
    """PRD §3.3: "Two windows that merely touch at a boundary are allowed only if
    the gap between them is at least the 1-day buffer; anything closer is rejected
    with `ERR_RENTAL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rental_window_buffer_overlap_halfopen
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, unit = _unit_with_first_reservation(api)
    validate_error(api.create_reservation(factories.reservation_payload(
        member["id"], unit["id"], "2026-08-05T00:00:00Z", "2026-08-08T00:00:00Z"),
        member_headers), ApiErrorId.ERR_RENTAL_WINDOW_CONFLICT.value)


def test_reservation_meeting_turnaround_buffer_allowed(api):
    """PRD §3.3: "The new window `[start_date, end_date)` conflicts with an
    existing window `[existing_start, existing_end)` when the new start is earlier
    than the existing end extended by 1 day, and the existing start is earlier
    than the new end extended by 1 day."

    Design: Difficulty/resource_temporal_overlap/rental_window_buffer_overlap_halfopen
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, unit = _unit_with_first_reservation(api)
    res2 = validate_success(api.create_reservation(factories.reservation_payload(
        member["id"], unit["id"], "2026-08-06T00:00:00Z", "2026-08-09T00:00:00Z"),
        member_headers), 201)
    assert res2["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / reservation_requires_unit_not_out_of_service
# ---------------------------------------------------------------------------

def test_reserving_out_of_service_unit_rejected(api):
    """PRD §3.3: "the referenced unit's `status` must not be `OUT_OF_SERVICE`,
    otherwise `ERR_RENTAL_UNIT_UNAVAILABLE`".

    Design: Difficulty/cross_entity_state_dependency/reservation_requires_unit_not_out_of_service
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit = fixtures.setup_reservation_with_unit(api)
    validate_success(api.service_rental_unit(unit["id"], {"action": "RETIRE"}, STAFF))
    validate_error(api.create_reservation(factories.reservation_payload(
        member["id"], unit["id"], "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z"),
        member_headers), ApiErrorId.ERR_RENTAL_UNIT_UNAVAILABLE.value)


def test_restored_unit_becomes_reservable_again(api):
    """PRD §3.3: "restore an `OUT_OF_SERVICE` unit with an `action` of `RESTORE`,
    moving it back to `AVAILABLE` with its `condition` reset to `GOOD`."

    Design: Difficulty/cross_entity_state_dependency/reservation_requires_unit_not_out_of_service
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit = fixtures.setup_reservation_with_unit(api)
    validate_success(api.service_rental_unit(unit["id"], {"action": "RETIRE"}, STAFF))
    validate_success(api.service_rental_unit(unit["id"], {"action": "RESTORE"}, STAFF))
    res = validate_success(api.create_reservation(factories.reservation_payload(
        member["id"], unit["id"], "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z"),
        member_headers), 201)
    assert res["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / rental_units_conserved_on_pickup_return
# ---------------------------------------------------------------------------

def test_good_return_closes_reservation_and_frees_unit(api):
    """PRD §3.3: "A good return of a `PICKED_UP` reservation moves it to
    `RETURNED` and then immediately to the terminal `CLOSED` state, and moves the
    unit from `RENTED_OUT` back to `AVAILABLE`."

    Design: Difficulty/compensating_invariant/rental_units_conserved_on_pickup_return
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit, res = fixtures.setup_picked_up_reservation(
        api, base_daily_rate_cents=2000, replacement_value_cents=35000,
        start_date="2026-07-05T00:00:00Z", end_date="2026-07-06T00:00:00Z")
    res = validate_success(api.return_reservation(res["id"], {"condition": "GOOD"}, STAFF))
    assert res["status"] == "CLOSED"
    unit = validate_success(api.get_rental_unit(unit["id"], STAFF))
    assert unit["status"] == "AVAILABLE"


def test_available_unit_count_conserved_after_pickup_return(api):
    """PRD §2.8: "A pickup moves one unit from `AVAILABLE` to `RENTED_OUT`; the
    paired good return moves it back, restoring the available count."

    Design: Difficulty/compensating_invariant/rental_units_conserved_on_pickup_return
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit, res = fixtures.setup_picked_up_reservation(
        api, base_daily_rate_cents=2000, replacement_value_cents=35000,
        start_date="2026-07-05T00:00:00Z", end_date="2026-07-06T00:00:00Z")
    validate_success(api.return_reservation(res["id"], {"condition": "GOOD"}, STAFF))
    data, meta = validate_paginated(api.list_rental_units(
        STAFF, params={"product_id": product["id"], "status": "AVAILABLE"}))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / rental_damage_cascade_depth2
# ---------------------------------------------------------------------------

def test_damaged_return_takes_unit_out_of_service(api):
    """PRD §3.3: "A damaged return of a `PICKED_UP` reservation instead cascades:
    the reservation moves to `DAMAGE_ASSESSED`; the unit moves from `RENTED_OUT`
    to `OUT_OF_SERVICE` with its `condition` set to `DAMAGED`".

    Design: Difficulty/transitive_cascade/rental_damage_cascade_depth2
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit, res = fixtures.setup_picked_up_reservation(api)
    res = validate_success(api.return_reservation(res["id"], {"condition": "DAMAGED"}, STAFF))
    assert res["status"] == "DAMAGE_ASSESSED"
    unit = validate_success(api.get_rental_unit(unit["id"], STAFF))
    assert unit["status"] == "OUT_OF_SERVICE"
    assert unit["condition"] == "DAMAGED"


def test_damaged_return_auto_creates_repair_order(api):
    """PRD §3.3: "and a repair order is auto-created for that unit with its
    `rental_unit_id` set, its `repair_stage` at `RECEIVED`, and its
    `billing_stage` at `UNBILLED`."

    Design: Difficulty/transitive_cascade/rental_damage_cascade_depth2
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit, res = fixtures.setup_picked_up_reservation(api)
    validate_success(api.return_reservation(res["id"], {"condition": "DAMAGED"}, STAFF))
    data, meta = validate_paginated(api.list_repair_orders(
        STAFF, params={"rental_unit_id": unit["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["repair_stage"] == "RECEIVED"
    assert data[0]["billing_stage"] == "UNBILLED"


# ---------------------------------------------------------------------------
# Queue B — state_machines / cancel_reservation_from_cancelled_returns_invalid_state
# ---------------------------------------------------------------------------

def test_cancel_already_cancelled_reservation_rejected(api):
    """PRD §3.3: "A member may cancel a still-`RESERVED` reservation, moving it to
    the terminal `CANCELLED` state and releasing the held window without touching
    the unit's status; cancelling anything not `RESERVED` yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_reservation_from_cancelled_returns_invalid_state
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit, res = fixtures.setup_reservation(api)
    validate_success(api.cancel_reservation(res["id"], member_headers))
    validate_error(api.cancel_reservation(res["id"], member_headers),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue B — validations / reservation_invalid_interval_returns_422
# ---------------------------------------------------------------------------

def test_reservation_end_before_start_rejected(api):
    """PRD §3.3: "and `end_date` must be strictly after `start_date`, otherwise
    `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/reservation_invalid_interval_returns_422
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit = fixtures.setup_reservation_with_unit(api)
    validate_error(api.create_reservation(factories.reservation_payload(
        member["id"], unit["id"], "2026-07-10T00:00:00Z", "2026-07-08T00:00:00Z"),
        member_headers), ApiErrorId.ERR_INVALID_INTERVAL.value)


# ---------------------------------------------------------------------------
# Queue B — entities / rental_unit_reverse_reachable_by_product
# ---------------------------------------------------------------------------

def test_rental_units_listable_by_product_id(api):
    """PRD §2.3: "The `meta` block of a list response reports `limit`, `offset`,
    `total_count` (the total number of records matching the filter, ignoring
    pagination), and `has_more`".

    Design: Corner/entities/rental_unit_reverse_reachable_by_product
    """
    product = fixtures.create_rentable_product(api)
    unit = fixtures.create_rental_unit(api, product["id"])
    data, meta = validate_paginated(api.list_rental_units(
        STAFF, params={"product_id": product["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == unit["id"]


# ---------------------------------------------------------------------------
# Queue B — consistency_model / reservation_immediately_readable
# ---------------------------------------------------------------------------

def test_created_reservation_immediately_readable(api):
    """PRD §3.3: "At creation the reservation's `rental_fee_cents` is computed and
    pinned in a fixed order."

    Design: Corner/consistency_model/reservation_immediately_readable
    """
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers, product, unit = fixtures.setup_reservation_with_unit(
        api, base_daily_rate_cents=3000, replacement_value_cents=100000)
    created = validate_success(api.create_reservation(factories.reservation_payload(
        member["id"], unit["id"], "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z"),
        member_headers), 201)
    fetched = validate_success(api.get_reservation(created["id"], member_headers))
    assert fetched["status"] == "RESERVED"
    assert fetched["rental_fee_cents"] == 11250
