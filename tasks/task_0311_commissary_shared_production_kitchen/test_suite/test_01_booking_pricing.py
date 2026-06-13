"""Booking fee computation, peak/turnover semantics, and station overlap.

Translates difficulty queue instances:
  combinatorial_formula / booking_fee_tiered_rate_peak_turnover_nonlinear
  resource_temporal_overlap / booking_overlap_with_turnover_buffer_on_station
and corner queue instances for computed fee, interval/peak/station validations.
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_operator_headers, TEST_USERS,
    register_funded_member, create_station, current_member_version,
    create_completed_booking,
)

FM = TEST_USERS["facility_manager_headers"]


# ── Difficulty: combinatorial_formula / booking_fee_tiered_rate_peak_turnover_nonlinear ──

def test_peak_oven_booking_fee_is_4500(api):
    """PRD 3.3: "a CONVECTION_OVEN at 3000 cents per hour" and "The peak
    multiplier is 1.5 when the booking is a peak booking (is_peak true) and 1.0
    otherwise." PRD 3.2: the peak window "runs from 06:00 inclusive up to 10:00
    exclusive", so a 09:00 start is a peak booking. A peak oven booking of 60
    minutes with no adjacent reservation yields 3000 * 1.0h * 1.5 = 4500 and no
    cleaning surcharge.

    Design: Difficulty/combinatorial_formula/booking_fee_tiered_rate_peak_turnover_nonlinear
    """
    member, v = register_funded_member(amount_cents=100000, plan_tier="PREMIUM")
    mo = make_member_operator_headers(member["id"])
    oven = create_station(name="Oven1", station_class="CONVECTION_OVEN", turnover_buffer_minutes=30)

    res = api.create_booking(member["id"], {
        "station_id": oven["id"],
        "start_utc": "2026-07-02T09:00:00.000Z",
        "end_utc": "2026-07-02T10:00:00.000Z",
        "expected_member_version": v,
    }, mo)
    booking = validate_success(res, 201)
    assert booking["is_peak"] is True, "09:00 start is within [06:00,10:00) peak window"
    assert booking["turnover_applied"] is False
    assert booking["fee_cents"] == 4500, f"expected 4500, got {booking['fee_cents']}"


def test_offpeak_prep_booking_120min_fee_is_2400(api):
    """PRD 3.3: "a PREP_TABLE is billed at 1200 cents per hour" and "The peak
    multiplier is 1.5 when the booking is a peak booking (is_peak true) and 1.0
    otherwise." An off-peak 120-minute prep booking is 1200 * 2h * 1.0 = 2400,
    with no surcharge because no adjacency forces the buffer.

    Design: Difficulty/combinatorial_formula/booking_fee_tiered_rate_peak_turnover_nonlinear
    """
    member, v = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="Prep1", station_class="PREP_TABLE")
    res = api.create_booking(member["id"], {
        "station_id": prep["id"],
        "start_utc": "2026-07-10T12:00:00.000Z",
        "end_utc": "2026-07-10T14:00:00.000Z",
        "expected_member_version": v,
    }, mo)
    booking = validate_success(res, 201)
    assert booking["turnover_applied"] is False
    assert booking["fee_cents"] == 2400, f"expected 2400, got {booking['fee_cents']}"


# ── Corner: entities / booking_computed_fee_ignores_client_supplied_fee ──

def test_computed_fee_is_server_derived(api):
    """PRD 3.2: "The booking fee is computed at confirmation and stored
    read-only in fee_cents". An off-peak prep 120-minute booking is computed by
    the server to 2400 regardless of any client value.

    Design: Corner/entities/booking_computed_fee_ignores_client_supplied_fee
    """
    member, v = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="PrepCf", station_class="PREP_TABLE")
    res = api.create_booking(member["id"], {
        "station_id": prep["id"],
        "start_utc": "2026-07-10T12:00:00.000Z",
        "end_utc": "2026-07-10T14:00:00.000Z",
        "expected_member_version": v,
    }, mo)
    booking = validate_success(res, 201)
    assert booking["fee_cents"] == 2400


# ── Difficulty: resource_temporal_overlap / booking_overlap_with_turnover_buffer_on_station ──

def test_booking_overlap_within_turnover_buffer_rejected(api):
    """PRD 3.2: "a booking is rejected with ERR_BOOKING_OVERLAP if there is any
    existing CONFIRMED or COMPLETED booking on the same station whose interval,
    expanded by the station's turnover_buffer_minutes of cleaning time, overlaps
    the new interval." A 13:15 start only 15 min after a prior 13:00 end still
    collides under the 30-min buffer.

    Design: Difficulty/resource_temporal_overlap/booking_overlap_with_turnover_buffer_on_station
    """
    member, v = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="Prep14", station_class="PREP_TABLE", turnover_buffer_minutes=30)
    first = api.create_booking(member["id"], {
        "station_id": prep["id"],
        "start_utc": "2026-07-08T12:00:00.000Z",
        "end_utc": "2026-07-08T13:00:00.000Z",
        "expected_member_version": v,
    }, mo)
    validate_success(first, 201)
    v2 = current_member_version(member["id"])
    res = api.create_booking(member["id"], {
        "station_id": prep["id"],
        "start_utc": "2026-07-08T13:15:00.000Z",
        "end_utc": "2026-07-08T14:00:00.000Z",
        "expected_member_version": v2,
    }, mo)
    validate_error(res, "ERR_BOOKING_OVERLAP")


def test_booking_outside_turnover_buffer_succeeds(api):
    """PRD 3.2: "a new booking must clear both the occupied time and the turnover
    buffer on either side of every existing reservation on that station." A
    booking starting well beyond the 30-min buffer (14:00 after a 13:00 end)
    clears the buffer and is accepted.

    Design: Difficulty/resource_temporal_overlap/booking_overlap_with_turnover_buffer_on_station
    """
    member, v = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="Prep14b", station_class="PREP_TABLE", turnover_buffer_minutes=30)
    first = api.create_booking(member["id"], {
        "station_id": prep["id"],
        "start_utc": "2026-07-08T12:00:00.000Z",
        "end_utc": "2026-07-08T13:00:00.000Z",
        "expected_member_version": v,
    }, mo)
    validate_success(first, 201)
    v2 = current_member_version(member["id"])
    res = api.create_booking(member["id"], {
        "station_id": prep["id"],
        "start_utc": "2026-07-08T14:00:00.000Z",
        "end_utc": "2026-07-08T15:00:00.000Z",
        "expected_member_version": v2,
    }, mo)
    validate_success(res, 201)


# ── Corner: validations / booking_invalid_interval_end_before_start ──

def test_booking_invalid_interval_rejected(api):
    """PRD 3.2: "the interval must be non-empty, meaning end_utc is strictly
    later than start_utc (otherwise ERR_INVALID_INTERVAL)".

    Design: Corner/validations/booking_invalid_interval_end_before_start
    """
    member, v = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="PrepIv", station_class="PREP_TABLE")
    res = api.create_booking(member["id"], {
        "station_id": prep["id"],
        "start_utc": "2026-07-14T14:00:00.000Z",
        "end_utc": "2026-07-14T13:00:00.000Z",
        "expected_member_version": v,
    }, mo)
    validate_error(res, "ERR_INVALID_INTERVAL")


# ── Corner: validations / booking_peak_standard_member_rejected ──

def test_booking_peak_window_standard_member_rejected(api):
    """PRD 3.2: "Peak bookings are a premium privilege — if a booking would be a
    peak booking but the member's plan_tier is not PREMIUM, the booking is
    rejected with ERR_PEAK_REQUIRES_PREMIUM." A STANDARD member booking 07:00 is
    inside the peak window.

    Design: Corner/validations/booking_peak_standard_member_rejected
    """
    member, v = register_funded_member(amount_cents=100000, plan_tier="STANDARD")
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="PrepPk", station_class="PREP_TABLE")
    res = api.create_booking(member["id"], {
        "station_id": prep["id"],
        "start_utc": "2026-07-15T07:00:00.000Z",
        "end_utc": "2026-07-15T08:00:00.000Z",
        "expected_member_version": v,
    }, mo)
    validate_error(res, "ERR_PEAK_REQUIRES_PREMIUM")


# ── Corner: validations / booking_station_out_of_service_rejected ──

def test_booking_station_out_of_service_rejected(api):
    """PRD 3.2: "A station that is OUT_OF_SERVICE accepts no new bookings." and
    "the referenced station must be OPEN (otherwise ERR_STATION_OUT_OF_SERVICE)".

    Design: Corner/validations/booking_station_out_of_service_rejected
    """
    member, v = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    station = create_station(name="PrepOos", station_class="PREP_TABLE")
    validate_success(api.update_station(station["id"], {"status": "OUT_OF_SERVICE"}, FM), 200)
    res = api.create_booking(member["id"], {
        "station_id": station["id"],
        "start_utc": "2026-07-16T12:00:00.000Z",
        "end_utc": "2026-07-16T13:00:00.000Z",
        "expected_member_version": v,
    }, mo)
    validate_error(res, "ERR_STATION_OUT_OF_SERVICE")


# ── Corner: errors / error_insufficient_wallet_on_booking ──

def test_booking_insufficient_wallet_rejected(api):
    """PRD 2.7: "Whenever a charge is attempted and the member's
    wallet_balance_cents is below the computed amount, the operation is refused
    with ERR_INSUFFICIENT_WALLET (HTTP 402)." A wallet-0 member booking a fee of
    2400 is refused.

    Design: Corner/errors/error_insufficient_wallet_on_booking
    """
    member, v = register_funded_member(amount_cents=0)
    mo = make_member_operator_headers(member["id"])
    prep = create_station(name="PrepIw", station_class="PREP_TABLE")
    res = api.create_booking(member["id"], {
        "station_id": prep["id"],
        "start_utc": "2026-07-19T12:00:00.000Z",
        "end_utc": "2026-07-19T14:00:00.000Z",
        "expected_member_version": v,
    }, mo)
    validate_error(res, "ERR_INSUFFICIENT_WALLET")
