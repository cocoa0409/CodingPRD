"""Booking-time temporal and capacity validations: chair buffer overlap, stylist overlap,
operating windows, inactive service, reserved-chair conflicts, block chair/window mismatch,
and the state-over-temporal validation-priority pair.

Queue A (Difficulty): resource_temporal_overlap/rto_chair_overlap_with_turnover_buffer;
                      resource_temporal_overlap/rto_stylist_overlap_no_buffer_backtoback_allowed;
                      priority_pair_validation_conflict/ppv_state_vs_temporal_on_checkin_vs_booking.
Queue B (Corner): section `validations`.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_style_service, create_chair, create_stylist, create_member,
    setup_base_scenario, book_standalone_appointment, setup_completed_standalone,
    setup_confirmed_block, pay_deposit, confirm_block, current_block_version,
    TEST_USERS,
)

FD = TEST_USERS["front_desk_headers"]


# ─── Queue A: chair overlap WITH trailing turnover buffer ─────────────────────

def test_chair_overlap_blocked_by_trailing_buffer(api):
    """PRD §3.4: "the half-open interval from `start_minute` up to but not including
    `end_minute` plus the chair's `turnover_buffer_minutes` must not overlap any
    non-terminal appointment on that chair — the buffer trails each appointment — and an
    overlap faults with `ERR_CHAIR_DOUBLE_BOOKED` (409)."

    First appt [600,645) on a 10-min-buffer chair reserves through 655. A second booking at
    650 (raw intervals [600,645) and [650,695) do not overlap, but the buffer does) is
    rejected.

    Design: Difficulty/resource_temporal_overlap/rto_chair_overlap_with_turnover_buffer
    """
    service = create_style_service(base_duration_minutes=45, base_price_cents=6000)
    chair = create_chair(turnover_buffer_minutes=10)
    s1 = create_stylist(full_name="S One")
    s2 = create_stylist(full_name="S Two")
    m1 = create_member(full_name="M1")
    m2 = create_member(full_name="M2")
    validate_success(api.create_appointment(
        {"member_id": m1["id"], "chair_id": chair["id"], "stylist_id": s1["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT"},
        FD), 201)
    res = api.create_appointment(
        {"member_id": m2["id"], "chair_id": chair["id"], "stylist_id": s2["id"],
         "style_service_id": service["id"], "start_minute": 650, "payment_method": "CREDIT"},
        FD)
    validate_error(res, "ERR_CHAIR_DOUBLE_BOOKED", expected_status=409)


def test_chair_booking_exactly_at_buffer_end_allowed(api):
    """PRD §3.4: "the half-open interval from `start_minute` up to but not including
    `end_minute` plus the chair's `turnover_buffer_minutes` must not overlap any
    non-terminal appointment on that chair — the buffer trails each appointment ..."

    First appt [600,645) on a 10-min-buffer chair reserves through 655 (exclusive). A second
    booking starting exactly at 655 does not overlap the half-open buffered interval and is
    accepted.

    Design: Difficulty/resource_temporal_overlap/rto_chair_overlap_with_turnover_buffer
    """
    service = create_style_service(base_duration_minutes=45, base_price_cents=6000)
    chair = create_chair(turnover_buffer_minutes=10)
    s1 = create_stylist(full_name="S One")
    s2 = create_stylist(full_name="S Two")
    m1 = create_member(full_name="M1")
    m2 = create_member(full_name="M2")
    validate_success(api.create_appointment(
        {"member_id": m1["id"], "chair_id": chair["id"], "stylist_id": s1["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT"},
        FD), 201)
    res = api.create_appointment(
        {"member_id": m2["id"], "chair_id": chair["id"], "stylist_id": s2["id"],
         "style_service_id": service["id"], "start_minute": 655, "payment_method": "CREDIT"},
        FD)
    validate_success(res, 201)


# ─── Queue A: stylist overlap WITHOUT buffer; back-to-back allowed ────────────

def test_stylist_overlap_rejected_without_buffer(api):
    """PRD §3.4: "The stylist must be free too: the half-open interval from `start_minute`
    up to but not including `end_minute` must not overlap any non-terminal appointment for
    that stylist, with no buffer, so back-to-back bookings are allowed; an overlap faults
    with `ERR_STYLIST_DOUBLE_BOOKED` (409)."

    Same stylist, first [600,645), second starting at 630 overlaps -> rejected.

    Design: Difficulty/resource_temporal_overlap/rto_stylist_overlap_no_buffer_backtoback_allowed
    """
    service = create_style_service(base_duration_minutes=45, base_price_cents=6000)
    chair_a = create_chair(label="Chair A")
    chair_b = create_chair(label="Chair B")
    stylist = create_stylist(full_name="Solo Stylist")
    m1 = create_member(full_name="M1")
    m2 = create_member(full_name="M2")
    validate_success(api.create_appointment(
        {"member_id": m1["id"], "chair_id": chair_a["id"], "stylist_id": stylist["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT"},
        FD), 201)
    res = api.create_appointment(
        {"member_id": m2["id"], "chair_id": chair_b["id"], "stylist_id": stylist["id"],
         "style_service_id": service["id"], "start_minute": 630, "payment_method": "CREDIT"},
        FD)
    validate_error(res, "ERR_STYLIST_DOUBLE_BOOKED", expected_status=409)


def test_stylist_backtoback_at_end_minute_allowed(api):
    """PRD §3.4: "the half-open interval from `start_minute` up to but not including
    `end_minute` must not overlap any non-terminal appointment for that stylist, with no
    buffer, so back-to-back bookings are allowed ..."

    Same stylist, first [600,645), second starting exactly at 645 (different chair) is
    accepted (adjacency permitted, half-open interval).

    Design: Difficulty/resource_temporal_overlap/rto_stylist_overlap_no_buffer_backtoback_allowed
    """
    service = create_style_service(base_duration_minutes=45, base_price_cents=6000)
    chair_a = create_chair(label="Chair A")
    chair_b = create_chair(label="Chair B")
    stylist = create_stylist(full_name="Solo Stylist")
    m1 = create_member(full_name="M1")
    m2 = create_member(full_name="M2")
    validate_success(api.create_appointment(
        {"member_id": m1["id"], "chair_id": chair_a["id"], "stylist_id": stylist["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT"},
        FD), 201)
    res = api.create_appointment(
        {"member_id": m2["id"], "chair_id": chair_b["id"], "stylist_id": stylist["id"],
         "style_service_id": service["id"], "start_minute": 645, "payment_method": "CREDIT"},
        FD)
    validate_success(res, 201)


# ─── Queue A: state (p6) precedence over temporal pair on a completed appt ────

def test_cancel_completed_appointment_returns_not_cancellable(api):
    """PRD §3.9: "Cancellation requires the appointment to be in `BOOKED` or `CHECKED_IN`
    (otherwise `ERR_APPOINTMENT_NOT_CANCELLABLE`, 409) ..."

    A cancel on a COMPLETED appointment violates the state precondition and returns
    ERR_APPOINTMENT_NOT_CANCELLABLE (409).

    Design: Difficulty/priority_pair_validation_conflict/ppv_state_vs_temporal_on_checkin_vs_booking
    """
    scenario, appt = setup_completed_standalone()
    res = api.cancel_appointment(appt["id"], FD)
    validate_error(res, "ERR_APPOINTMENT_NOT_CANCELLABLE", expected_status=409)


def test_cancel_no_show_appointment_returns_not_cancellable(api):
    """PRD §3.9: "Cancellation requires the appointment to be in `BOOKED` or `CHECKED_IN`
    (otherwise `ERR_APPOINTMENT_NOT_CANCELLABLE`, 409) ..."

    A cancel on a NO_SHOW (terminal) appointment likewise fails the state precondition with
    ERR_APPOINTMENT_NOT_CANCELLABLE (409) — the state check (p6) governs the cancel path.

    Design: Difficulty/priority_pair_validation_conflict/ppv_state_vs_temporal_on_checkin_vs_booking
    """
    from test_helpers import set_clock
    scenario = setup_base_scenario()
    set_clock("2026-01-01T11:00:00Z")
    appt = book_standalone_appointment(scenario, start_minute=600)
    validate_success(api.no_show_appointment(appt["id"], FD), 200)
    res = api.cancel_appointment(appt["id"], FD)
    validate_error(res, "ERR_APPOINTMENT_NOT_CANCELLABLE", expected_status=409)


# ─── Queue B: operating window / inactive service / reserved chair / mismatch ─

def test_booking_outside_chair_window_rejected(api):
    """PRD §3.4: "The appointment window must lie within both the chair's operating hours,
    the half-open interval from `open_minute` up to but not including `close_minute` ... a
    window outside either faults with `ERR_OUTSIDE_OPERATING_WINDOW` (422)."

    start 1180 + 45-min service ends 1225 > chair close 1200 -> rejected.

    Design: Corner/validations/val_booking_outside_chair_window_rejected
    """
    scenario = setup_base_scenario(
        service_overrides={"base_duration_minutes": 45},
        chair_overrides={"open_minute": 480, "close_minute": 1200},
        stylist_overrides={"shift_start_minute": 480, "shift_end_minute": 1200})
    res = api.create_appointment(
        {"member_id": scenario["member"]["id"], "chair_id": scenario["chair"]["id"],
         "stylist_id": scenario["stylist"]["id"],
         "style_service_id": scenario["service"]["id"],
         "start_minute": 1180, "payment_method": "CREDIT"}, FD)
    validate_error(res, "ERR_OUTSIDE_OPERATING_WINDOW", expected_status=422)


def test_booking_inactive_service_rejected(api):
    """PRD §3.4: "The service must be active and the subject member must be `ACTIVE`; an
    inactive service or add-on (or attempting to attach one) faults with
    `ERR_SERVICE_OR_ADDON_INACTIVE` (409) ..."

    Design: Corner/validations/val_inactive_service_booking_rejected
    """
    scenario = setup_base_scenario(service_overrides={"active": False})
    res = api.create_appointment(
        {"member_id": scenario["member"]["id"], "chair_id": scenario["chair"]["id"],
         "stylist_id": scenario["stylist"]["id"],
         "style_service_id": scenario["service"]["id"],
         "start_minute": 600, "payment_method": "CREDIT"}, FD)
    validate_error(res, "ERR_SERVICE_OR_ADDON_INACTIVE", expected_status=409)


def test_standalone_on_reserved_chair_rejected(api):
    """PRD §3.4: "a standalone booking — one without a matching `event_block_id` — that
    lands on a chair reserved by a `CONFIRMED` block during that block's window is rejected
    with `ERR_CHAIR_RESERVED_FOR_BLOCK` (409), because a confirmed block holds its chairs
    exclusively."

    Design: Corner/validations/val_standalone_on_reserved_chair_rejected
    """
    # Build a CONFIRMED GROUP block reserving chair A over [540,900) with two appointments.
    ctx = setup_confirmed_block(stylist1_tier="SENIOR", stylist2_tier="SENIOR")
    walkin = create_member(full_name="Walkin")
    s3 = create_stylist(full_name="S3")
    res = api.create_appointment(
        {"member_id": walkin["id"], "chair_id": ctx["chair_a"]["id"],
         "stylist_id": s3["id"], "style_service_id": ctx["service"]["id"],
         "start_minute": 700, "payment_method": "CREDIT"}, FD)
    validate_error(res, "ERR_CHAIR_RESERVED_FOR_BLOCK", expected_status=409)


def test_block_appointment_wrong_chair_rejected(api):
    """PRD §3.4: "If an `event_block_id` is supplied, the chosen `chair_id` must be among
    that block's `reserved_chair_ids` and the appointment window must fall within the block
    window ... a chair or window that does not match faults with
    `ERR_BLOCK_CHAIR_OR_WINDOW_MISMATCH` (422)."

    Design: Corner/validations/val_block_appointment_wrong_chair_rejected
    """
    service = create_style_service()
    chair_a = create_chair(label="Chair A")
    chair_c = create_chair(label="Chair C")  # not reserved by the block
    s1 = create_stylist(full_name="S1")
    org = create_member(full_name="Org")
    block = validate_success(api.create_event_block(
        {"organizer_member_id": org["id"], "block_type": "GROUP",
         "window_start_minute": 540, "window_end_minute": 900,
         "reserved_chair_ids": [chair_a["id"]], "party_size": 2}, FD), 201)
    res = api.create_appointment(
        {"member_id": org["id"], "chair_id": chair_c["id"], "stylist_id": s1["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT",
         "event_block_id": block["id"], "expected_event_block_version": block["version"]}, FD)
    validate_error(res, "ERR_BLOCK_CHAIR_OR_WINDOW_MISMATCH", expected_status=422)
