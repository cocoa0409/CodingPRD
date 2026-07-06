"""Booking guards: safety recall, technician duty status, and window validity."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_appointment_payload,
    provision_base, create_and_activate_recall, set_technician_off_duty, get_service_request,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _book(api, ctx, window_start="2026-06-10T09:00:00Z", window_end="2026-06-10T10:00:00Z"):
    return api.create_appointment(
        ctx["sr_id"],
        create_appointment_payload(ctx["tech_id"], ctx["zone_id"], window_start, window_end),
        DISPATCHER)


# ─── Difficulty: schedule_blocked_by_appliance_recall ──────────────────────
def test_booking_recalled_appliance_rejected(api):
    """PRD §3.2: "The appliance must not be under an active recall — a `RECALLED` appliance
    is rejected with `ERR_SAFETY_RECALL_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_appliance_recall
    """
    # Recall the appliance BEFORE opening the request, so the request is born in
    # INTAKE on an already-RECALLED appliance (recalling afterward would cascade the
    # in-flight request to SAFETY_HOLD per PRD §2.6).
    ctx = provision_base(model="MD10", recall=True)  # appliance RECALLED, request INTAKE
    validate_error(_book(api, ctx), ApiErrorId.ERR_SAFETY_RECALL_HOLD)


def test_booking_blocked_by_recall_leaves_request_in_intake(api):
    """PRD §3.2: "Booking from `INTAKE` advances the request `INTAKE → SCHEDULED`".
    PRD §3.2: "The appliance must not be under an active recall — a `RECALLED` appliance
    is rejected with `ERR_SAFETY_RECALL_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_appliance_recall
    """
    # Recall the appliance BEFORE opening the request, so the request is born in
    # INTAKE on an already-RECALLED appliance (recalling afterward would cascade the
    # in-flight request to SAFETY_HOLD per PRD §2.6).
    ctx = provision_base(model="MD10", recall=True)  # appliance RECALLED, request INTAKE
    validate_error(_book(api, ctx), ApiErrorId.ERR_SAFETY_RECALL_HOLD)
    sr = get_service_request(ctx)
    assert sr["status"] == "INTAKE", "a rejected booking must not advance the request"


# ─── Difficulty: schedule_blocked_by_technician_off_duty ───────────────────
def test_booking_off_duty_technician_rejected(api):
    """PRD §3.2: "The named technician must be `ON_DUTY`, or the booking is rejected with
    `ERR_TECHNICIAN_OFF_DUTY`."

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_technician_off_duty
    """
    ctx = provision_base(model="ME10")
    set_technician_off_duty(ctx)
    validate_error(_book(api, ctx), ApiErrorId.ERR_TECHNICIAN_OFF_DUTY)


def test_off_duty_booking_leaves_request_in_intake(api):
    """PRD §3.2: "The named technician must be `ON_DUTY`, or the booking is rejected with
    `ERR_TECHNICIAN_OFF_DUTY`."
    PRD §3.2: "Booking from `INTAKE` advances the request `INTAKE → SCHEDULED`".

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_technician_off_duty
    """
    ctx = provision_base(model="ME10")
    set_technician_off_duty(ctx)
    validate_error(_book(api, ctx), ApiErrorId.ERR_TECHNICIAN_OFF_DUTY)
    sr = get_service_request(ctx)
    assert sr["status"] == "INTAKE"


# ─── Corner: appointment_window_end_before_start_returns_validation ────────
def test_booking_window_end_not_after_start_rejected(api):
    """PRD §3.2: "The window is a half-open interval `[window_start, window_end)`, and
    `window_end` must be strictly after `window_start`, otherwise the request is rejected
    with `ERR_VALIDATION`."

    Design: Corner/validations/appointment_window_end_before_start_returns_validation
    """
    ctx = provision_base(model="ND0")
    res = _book(api, ctx, window_start="2026-06-10T10:00:00Z", window_end="2026-06-10T09:00:00Z")
    validate_error(res, ApiErrorId.ERR_VALIDATION)
