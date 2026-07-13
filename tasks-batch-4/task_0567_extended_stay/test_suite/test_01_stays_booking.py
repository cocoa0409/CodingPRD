"""Stay booking: creation round-trip, required/shape validation, and the
booking-time temporal / minimum-term gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_rate_plan, create_unit,
    create_rate_plan_payload, create_unit_payload, create_stay_payload,
    assert_stay, TEST_USERS, MISSING_UUID,
)

PM = TEST_USERS["property_manager_headers"]


def test_create_and_read_stay_roundtrip(api):
    """PRD §3.3: "It is booked by a `PropertyManager` or a `CorporateAdmin` and
    enters `RESERVED` status."
    PRD §3.3: "The `planned_nights` figure is the whole number of 24-hour days
    between `move_in` and `planned_move_out` — the calendar-date difference of the
    two UTC midnights."
    PRD §3.3: "At creation the server computes `planned_nights`, sets
    `deposit_charged_cents` to 0 and `deposit_refundable_cents` equal to
    `deposit_held_cents`"

    Design: Corner/entities/create_and_read_stay_roundtrip
    """
    rate_plan = create_rate_plan(api)
    unit = create_unit(api)
    created = validate_success(api.create_stay(
        create_stay_payload(unit["id"], rate_plan["id"],
                            move_in="2026-05-01T00:00:00Z",
                            planned_move_out="2026-06-30T00:00:00Z",
                            deposit_held_cents=50000),
        PM,
    ), expected_status=201)

    fetched = validate_success(api.get_stay(created["id"], PM))
    assert_stay(fetched)
    assert fetched["status"] == "RESERVED"
    assert fetched["planned_nights"] == 60
    assert fetched["deposit_refundable_cents"] == 50000
    assert fetched["version"] == 1


def test_get_stay_not_found_returns_404(api):
    """PRD §2.8: "the server resolves them left to right and rejects the first one
    that does not exist with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_stay_not_found_returns_404
    """
    resp = api.get_stay(MISSING_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_missing_required_field_on_stay_create(api):
    """PRD §2.8: "required fields present, enum fields within their declared sets,
    dates parseable, pagination within range. A malformed body yields
    `ERR_VALIDATION` (400)"

    Design: Corner/entities/error_missing_required_field_on_stay_create
    """
    rate_plan = create_rate_plan(api)
    payload = {
        "rate_plan_id": rate_plan["id"],
        "move_in": "2026-05-01T00:00:00Z",
        "planned_move_out": "2026-06-30T00:00:00Z",
        "deposit_held_cents": 0,
    }  # unit_id omitted
    resp = api.create_stay(payload, PM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_invalid_date_range_on_stay_create(api):
    """PRD §3.3: "`planned_move_out` must be strictly later than `move_in`; a
    window that ends on or before it starts is rejected with
    `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/error_invalid_date_range_on_stay_create
    """
    rate_plan = create_rate_plan(api)
    unit = create_unit(api)
    resp = api.create_stay(
        create_stay_payload(unit["id"], rate_plan["id"],
                            move_in="2026-06-30T00:00:00Z",
                            planned_move_out="2026-05-01T00:00:00Z",
                            deposit_held_cents=0),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)


def test_new_unit_defaults_to_available_status(api):
    """PRD §3.1: "Every unit is created in `AVAILABLE` status and moves through the
    cycle `AVAILABLE` → `OCCUPIED` → `TURNOVER` → `AVAILABLE` as stays come and go"

    Design: Corner/entities/system_field_unit_status_defaults_available
    """
    unit = validate_success(
        api.create_unit(create_unit_payload(name="U9", property_name="Cedar", bedrooms=3), PM),
        expected_status=201,
    )
    fetched = validate_success(api.get_unit(unit["id"], PM))
    assert fetched["status"] == "AVAILABLE"


# --- Minimum lease term: 29 rejected, 30 accepted (boundary) ---

def test_minimum_lease_term_below_boundary_rejected(api):
    """PRD §3.3: "`planned_nights` must be at least `MIN_LEASE_TERM_DAYS`, which is
    30 nights. A shorter reservation is rejected with `ERR_MIN_TERM_NOT_MET`."

    Design: Difficulty/boundary_precision_check/minimum_lease_term_30_day_boundary
    """
    rate_plan = create_rate_plan(api)
    unit = create_unit(api)
    resp = api.create_stay(
        create_stay_payload(unit["id"], rate_plan["id"],
                            move_in="2026-05-01T00:00:00Z",
                            planned_move_out="2026-05-30T00:00:00Z",  # 29 nights
                            deposit_held_cents=0),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_MIN_TERM_NOT_MET.value)


def test_minimum_lease_term_at_boundary_accepted(api):
    """PRD §3.3: "`planned_nights` must be at least `MIN_LEASE_TERM_DAYS`, which is
    30 nights. A shorter reservation is rejected with `ERR_MIN_TERM_NOT_MET`."
    PRD §3.3: "It is booked by a `PropertyManager` or a `CorporateAdmin` and enters
    `RESERVED` status."

    Design: Difficulty/boundary_precision_check/minimum_lease_term_30_day_boundary
    """
    rate_plan = create_rate_plan(api)
    unit = create_unit(api)
    created = validate_success(api.create_stay(
        create_stay_payload(unit["id"], rate_plan["id"],
                            move_in="2026-05-01T00:00:00Z",
                            planned_move_out="2026-05-31T00:00:00Z",  # 30 nights
                            deposit_held_cents=0),
        PM,
    ), expected_status=201)
    fetched = validate_success(api.get_stay(created["id"], PM))
    assert fetched["planned_nights"] == 30
    assert fetched["status"] == "RESERVED"


# --- Unit occupancy separation: gap 0 rejected, gap 1 (buffer) accepted ---

def test_unit_adjacent_booking_gap_zero_rejected(api):
    """PRD §3.3: "Two windows that overlap, and two windows that merely touch
    end-to-start (the new stay beginning on the very day a prior stay ends), are
    both rejected with `ERR_UNIT_TIME_CONFLICT`: for a unit, adjacency is forbidden
    and at least one full day of separation is required."

    Design: Difficulty/resource_temporal_overlap/unit_overlap_with_turnover_buffer
    """
    rate_plan = create_rate_plan(api)
    unit = create_unit(api)
    validate_success(api.create_stay(
        create_stay_payload(unit["id"], rate_plan["id"],
                            move_in="2026-05-01T00:00:00Z",
                            planned_move_out="2026-06-30T00:00:00Z",
                            deposit_held_cents=0),
        PM,
    ), expected_status=201)
    # new stay starts exactly on the prior stay's move-out (gap 0)
    resp = api.create_stay(
        create_stay_payload(unit["id"], rate_plan["id"],
                            move_in="2026-06-30T00:00:00Z",
                            planned_move_out="2026-08-29T00:00:00Z",
                            deposit_held_cents=0),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_TIME_CONFLICT.value)


def test_unit_booking_with_one_day_buffer_accepted(api):
    """PRD §3.3: "Two windows that overlap, and two windows that merely touch
    end-to-start (the new stay beginning on the very day a prior stay ends), are
    both rejected with `ERR_UNIT_TIME_CONFLICT`: for a unit, adjacency is forbidden
    and at least one full day of separation is required."

    Design: Difficulty/resource_temporal_overlap/unit_overlap_with_turnover_buffer
    """
    rate_plan = create_rate_plan(api)
    unit = create_unit(api)
    validate_success(api.create_stay(
        create_stay_payload(unit["id"], rate_plan["id"],
                            move_in="2026-05-01T00:00:00Z",
                            planned_move_out="2026-06-30T00:00:00Z",
                            deposit_held_cents=0),
        PM,
    ), expected_status=201)
    # new stay starts one day after the prior stay's move-out (gap == buffer)
    created = validate_success(api.create_stay(
        create_stay_payload(unit["id"], rate_plan["id"],
                            move_in="2026-07-01T00:00:00Z",
                            planned_move_out="2026-08-30T00:00:00Z",
                            deposit_held_cents=0),
        PM,
    ), expected_status=201)
    fetched = validate_success(api.get_stay(created["id"], PM))
    assert fetched["status"] == "RESERVED"
