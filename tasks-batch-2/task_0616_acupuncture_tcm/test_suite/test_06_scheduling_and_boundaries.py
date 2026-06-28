"""Room/practitioner temporal availability and numeric boundary precision.

Covers the resource-temporal-overlap difficulty instances (room cleanup buffer,
practitioner turnover gap), the boundary-precision difficulty instances (arrival
grace strict >, zero-credit empty pool), and the adjacent-zero-buffer corner instance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_practitioner_headers,
    create_practitioner, create_patient, create_room, setup_finalized_intake,
    setup_active_plan, setup_clinic_scenario, setup_package_scenario,
    book_appointment, book_package_appointment, get_plan_version,
    create_appointment_payload,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def _book(ctx, patient, plan, practitioner_id, room_id, start, end):
    """Book a PER_VISIT appointment for an explicit (patient, plan) pair."""
    plv = get_plan_version(plan["id"])
    payload = create_appointment_payload(patient["id"], plan["id"], practitioner_id,
                                         room_id, plv, charge_source="PER_VISIT",
                                         base_fee_cents=12000,
                                         scheduled_start=start, scheduled_end=end)
    return api_book(payload)


def api_book(payload):
    from test_helpers import api_client
    return api_client.create_appointment(payload, ADMIN)


# ─── Room cleanup-buffer overlap (queue A) ─────────────────────────────────
def test_room_overlap_within_cleanup_buffer_rejected(api):
    """PRD 3.6: "each existing appointment on the same room_id occupies an extended
    interval running from its scheduled_start up to but not including its scheduled_end
    plus that room's cleanup_buffer_minutes converted to seconds; the new booking is
    rejected with ERR_ROOM_CONFLICT if its own half-open interval intersects any such
    extended interval on the same room."

    Design: Difficulty/resource_temporal_overlap/room_overlap_with_cleanup_buffer
    """
    pracA = create_practitioner()
    pracB = create_practitioner()
    room = create_room(room_name="Buffer Room", cleanup_buffer_minutes=30)

    p1 = create_patient(full_name="RA Pat")
    i1 = setup_finalized_intake(p1["id"], pracA["id"])
    pl1 = setup_active_plan(p1["id"], pracA["id"], i1["id"], acupoints=["LI4"])
    first = validate_success(_book(None, p1, pl1, pracA["id"], room["id"],
                                   "2026-06-10T10:00:00Z", "2026-06-10T10:45:00Z"), 201)
    assert first["clinical_status"] == "SCHEDULED"

    p2 = create_patient(full_name="RB Pat")
    i2 = setup_finalized_intake(p2["id"], pracB["id"])
    pl2 = setup_active_plan(p2["id"], pracB["id"], i2["id"], acupoints=["ST36"])
    # 11:00 falls inside the 10:45-11:15 cleanup tail of the same room.
    validate_error(_book(None, p2, pl2, pracB["id"], room["id"],
                         "2026-06-10T11:00:00Z", "2026-06-10T11:45:00Z"),
                   ApiErrorId.ERR_ROOM_CONFLICT.value)


def test_room_booking_after_cleanup_tail_succeeds(api):
    """PRD 3.6: "each existing appointment on the same room_id occupies an extended
    interval running from its scheduled_start up to but not including its scheduled_end
    plus that room's cleanup_buffer_minutes converted to seconds; the new booking is
    rejected with ERR_ROOM_CONFLICT if its own half-open interval intersects any such
    extended interval on the same room."

    Design: Difficulty/resource_temporal_overlap/room_overlap_with_cleanup_buffer
    """
    pracA = create_practitioner()
    pracB = create_practitioner()
    room = create_room(room_name="Buffer Room 2", cleanup_buffer_minutes=30)

    p1 = create_patient(full_name="RA2 Pat")
    i1 = setup_finalized_intake(p1["id"], pracA["id"])
    pl1 = setup_active_plan(p1["id"], pracA["id"], i1["id"], acupoints=["LI4"])
    validate_success(_book(None, p1, pl1, pracA["id"], room["id"],
                           "2026-06-10T10:00:00Z", "2026-06-10T10:45:00Z"), 201)

    p2 = create_patient(full_name="RB2 Pat")
    i2 = setup_finalized_intake(p2["id"], pracB["id"])
    pl2 = setup_active_plan(p2["id"], pracB["id"], i2["id"], acupoints=["ST36"])
    # 11:15 is exactly the end of the 10:45-11:15 cleanup tail; half-open → no intersect.
    second = validate_success(_book(None, p2, pl2, pracB["id"], room["id"],
                                    "2026-06-10T11:15:00Z", "2026-06-10T12:00:00Z"), 201)
    assert second["clinical_status"] == "SCHEDULED"


# ─── Practitioner turnover-gap overlap (queue A) ───────────────────────────
def test_practitioner_gap_below_turnover_buffer_rejected(api):
    """PRD 3.6: "two appointments on the same practitioner_id conflict when the new
    appointment's start is earlier than the existing appointment's end plus the
    practitioner's turnover_buffer_minutes (in seconds) and simultaneously the existing
    appointment's start is earlier than the new appointment's end plus that same buffer;
    such a conflict is rejected with ERR_PRACTITIONER_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/practitioner_gap_below_turnover_buffer
    """
    prac = create_practitioner(turnover_buffer_minutes=15)
    room1 = create_room(room_name="Room K1", cleanup_buffer_minutes=0)
    room2 = create_room(room_name="Room K2", cleanup_buffer_minutes=0)

    patient = create_patient(full_name="PG Pat")
    intake = setup_finalized_intake(patient["id"], prac["id"])
    plan = setup_active_plan(patient["id"], prac["id"], intake["id"], acupoints=["LI4"])

    validate_success(_book(None, patient, plan, prac["id"], room1["id"],
                           "2026-06-11T10:00:00Z", "2026-06-11T10:45:00Z"), 201)
    # Second appt starts at 10:45 (gap 0 < 15-min buffer) in a DIFFERENT room.
    validate_error(_book(None, patient, plan, prac["id"], room2["id"],
                         "2026-06-11T10:45:00Z", "2026-06-11T11:30:00Z"),
                   ApiErrorId.ERR_PRACTITIONER_CONFLICT.value)


def test_practitioner_gap_at_turnover_buffer_succeeds(api):
    """PRD 3.6: "two appointments on the same practitioner_id conflict when the new
    appointment's start is earlier than the existing appointment's end plus the
    practitioner's turnover_buffer_minutes (in seconds) and simultaneously the existing
    appointment's start is earlier than the new appointment's end plus that same buffer;
    such a conflict is rejected with ERR_PRACTITIONER_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/practitioner_gap_below_turnover_buffer
    """
    prac = create_practitioner(turnover_buffer_minutes=15)
    room1 = create_room(room_name="Room M1", cleanup_buffer_minutes=0)
    room2 = create_room(room_name="Room M2", cleanup_buffer_minutes=0)

    patient = create_patient(full_name="PG2 Pat")
    intake = setup_finalized_intake(patient["id"], prac["id"])
    plan = setup_active_plan(patient["id"], prac["id"], intake["id"], acupoints=["LI4"])

    validate_success(_book(None, patient, plan, prac["id"], room1["id"],
                           "2026-06-11T10:00:00Z", "2026-06-11T10:45:00Z"), 201)
    # Second starts at 11:00 — gap of exactly 15 minutes == buffer, not strictly less.
    second = validate_success(_book(None, patient, plan, prac["id"], room2["id"],
                                    "2026-06-11T11:00:00Z", "2026-06-11T11:45:00Z"), 201)
    assert second["clinical_status"] == "SCHEDULED"


# ─── Adjacent half-open intervals with zero buffer (corner) ────────────────
def test_room_adjacent_zero_buffer_no_conflict(api):
    """PRD 3.6: "Because the intervals are half-open and the buffers are applied as
    described, two appointments that are exactly adjacent with a zero buffer do not
    conflict."

    Design: Corner/calculations/room_adjacent_zero_buffer_no_conflict
    """
    pracA = create_practitioner()
    pracB = create_practitioner()
    room = create_room(room_name="Adj Room", cleanup_buffer_minutes=0)

    p1 = create_patient(full_name="X1 Pat")
    i1 = setup_finalized_intake(p1["id"], pracA["id"])
    pl1 = setup_active_plan(p1["id"], pracA["id"], i1["id"], acupoints=["LI4"])
    validate_success(_book(None, p1, pl1, pracA["id"], room["id"],
                           "2026-06-24T10:00:00Z", "2026-06-24T10:45:00Z"), 201)

    p2 = create_patient(full_name="X2 Pat")
    i2 = setup_finalized_intake(p2["id"], pracB["id"])
    pl2 = setup_active_plan(p2["id"], pracB["id"], i2["id"], acupoints=["ST36"])
    # Second starts exactly at the first's end; zero buffer → adjacent, no conflict.
    second = validate_success(_book(None, p2, pl2, pracB["id"], room["id"],
                                    "2026-06-24T10:45:00Z", "2026-06-24T11:30:00Z"), 201)
    assert second["clinical_status"] == "SCHEDULED"


# ─── Arrival grace boundary: strict greater-than (queue A) ─────────────────
def test_arrival_class_on_time_at_exact_grace_boundary(api):
    """PRD 3.5: "the arrival is classified LATE when that difference is strictly
    greater than the grace allowance of ten minutes, and ON_TIME otherwise. The
    boundary is strict — an arrival exactly ten minutes after the scheduled start (a
    difference of exactly six hundred seconds) is ON_TIME, and only a difference
    exceeding six hundred seconds is LATE."

    Design: Difficulty/boundary_precision_check/arrival_grace_boundary_strict_gt
    """
    ctx = setup_clinic_scenario()
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-08T10:00:00Z",
                            scheduled_end="2026-06-08T10:45:00Z")
    # Check in exactly 600s (10 min) after start → ON_TIME (strict >).
    get_success_data(api.set_clock("2026-06-08T10:10:00Z", ADMIN))
    result = validate_success(api.check_in(appt["id"], ADMIN), 200)
    assert result["arrival_class"] == "ON_TIME"
    assert result["clinical_status"] == "CHECKED_IN"


def test_arrival_class_late_one_second_past_boundary(api):
    """PRD 3.5: "only a difference exceeding six hundred seconds is LATE."

    Design: Difficulty/boundary_precision_check/arrival_grace_boundary_strict_gt
    """
    ctx = setup_clinic_scenario()
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-08T13:00:00Z",
                            scheduled_end="2026-06-08T13:45:00Z")
    # 601s after start → strictly greater than 600 → LATE.
    get_success_data(api.set_clock("2026-06-08T13:10:01Z", ADMIN))
    result = validate_success(api.check_in(appt["id"], ADMIN), 200)
    assert result["arrival_class"] == "LATE"


# ─── Zero-credit empty-pool boundary (queue A) ─────────────────────────────
def test_package_zero_credit_booking_rejected(api):
    """PRD 3.5: "a booking that would draw from a series with provisional_remaining_credits
    below 1 (or from a CANCELLED series) is rejected with ERR_NO_CREDITS_REMAINING."
    PRD 3.4: "When a booking debit drives provisional_remaining_credits to exactly 0,
    the series transitions from ACTIVE to EXHAUSTED, incrementing the series version."

    Design: Difficulty/boundary_precision_check/package_zero_credit_empty_set_boundary
    """
    ctx = setup_package_scenario(total_credits=1, price_paid_cents=9000)
    pkg_id = ctx["package"]["id"]
    # First booking consumes the only reservation → provisional 0, EXHAUSTED.
    book_package_appointment(ctx, pkg_id,
                             scheduled_start="2026-06-08T09:00:00Z",
                             scheduled_end="2026-06-08T09:45:00Z")
    series = get_success_data(api.get_package_series(pkg_id, ADMIN))
    assert series["provisional_remaining_credits"] == 0
    assert series["status"] == "EXHAUSTED"

    # Second booking at provisional 0 → rejected.
    plv = get_plan_version(ctx["plan"]["id"])
    payload = create_appointment_payload(
        ctx["patient"]["id"], ctx["plan"]["id"], ctx["practitioner"]["id"],
        ctx["room"]["id"], plv, charge_source="PACKAGE", package_series_id=pkg_id,
        base_fee_cents=0,
        scheduled_start="2026-06-08T11:00:00Z", scheduled_end="2026-06-08T11:45:00Z")
    validate_error(api.create_appointment(payload, ADMIN),
                   ApiErrorId.ERR_NO_CREDITS_REMAINING.value)


def test_package_booking_succeeds_at_one_credit(api):
    """PRD 3.5: "A package-funded booking additionally requires that the series have at
    least one provisional credit available and not be cancelled, as detailed in Section
    3.4; a booking that would draw from a series with provisional_remaining_credits below
    1 (or from a CANCELLED series) is rejected with ERR_NO_CREDITS_REMAINING."

    Design: Difficulty/boundary_precision_check/package_zero_credit_empty_set_boundary
    """
    ctx = setup_package_scenario(total_credits=1, price_paid_cents=9000)
    appt = book_package_appointment(ctx, ctx["package"]["id"],
                                    scheduled_start="2026-06-08T15:00:00Z",
                                    scheduled_end="2026-06-08T15:45:00Z")
    assert appt["clinical_status"] == "SCHEDULED"
    assert appt["charge_source"] == "PACKAGE"
