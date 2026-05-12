"""Test-driving endpoints: clock advance, payment-confirmed, script-authorization-revoked."""
from datetime import timedelta
from flask import Blueprint

from db import store, bump, parse_iso, DEPOSIT_HOLD_TTL_MINUTES
from middleware import require_role
from response import success_object
from validators import get_json_body, require_string, require_int
from errors import raise_error, ERR_BOOKING_NOT_FOUND, ERR_THEME_NOT_FOUND, ERR_INVALID_REQUEST
from clock import clock
from services import booking_service, slot_service

system_bp = Blueprint("system", __name__)


@system_bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    user_id, role = require_role("PlatformAdmin")
    body = get_json_body()
    to_ts = require_string(body, "to_timestamp")
    try:
        ts = parse_iso(to_ts)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "invalid to_timestamp")
    clock.advance_to(ts)

    # 1) For all SCHEDULED slots whose match_status==OPEN and now>=match_deadline_at, fail-match cascade
    for slot in list(store.session_slots.values()):
        if slot["schedule_status"] != "SCHEDULED":
            continue
        if slot["match_status"] != "OPEN":
            continue
        deadline = parse_iso(slot["match_deadline_at"])
        if ts >= deadline:
            slot_service.cancel_slot(slot, "SYSTEM_MATCH_FAIL", user_id, role, trigger="match_fail")

    # 2) For all PROMOTED bookings whose deposit hold TTL has elapsed without confirm-deposit, auto-cancel
    for b in list(store.bookings.values()):
        if b["status"] != "PENDING_DEPOSIT":
            continue
        promoted_at = b.get("promoted_at")
        if not promoted_at:
            continue
        try:
            pa = parse_iso(promoted_at)
        except Exception:
            continue
        if ts >= pa + timedelta(minutes=DEPOSIT_HOLD_TTL_MINUTES):
            slot = store.session_slots.get(b["slot_id"])
            if not slot:
                continue
            booking_service.cancel_booking(b, "SYSTEM_MATCH_FAIL", user_id, role,
                                           sweep_waitlist=True)

    return success_object({})


@system_bp.route("/_events/payment-confirmed", methods=["POST"])
def payment_confirmed_event():
    user_id, role = require_role("PaymentGateway", "PlatformAdmin")
    body = get_json_body()
    booking_id = require_string(body, "booking_id")
    idem = body.get("idempotency_key")
    b = store.bookings.get(booking_id)
    if not b:
        raise_error(ERR_BOOKING_NOT_FOUND, "booking not found")
    booking_service.confirm_booking_deposit(b, user_id, role, idem)
    from routes.bookings import booking_view
    return success_object(booking_view(b))


@system_bp.route("/_events/script-authorization-revoked", methods=["POST"])
def script_authorization_revoked():
    user_id, role = require_role("PlatformAdmin")
    body = get_json_body()
    theme_id = require_string(body, "theme_id")
    revoked_version = require_int(body, "revoked_version", 1, 1_000_000)
    theme = store.themes.get(theme_id)
    if not theme:
        raise_error(ERR_THEME_NOT_FOUND, "theme not found")
    # Cancel slots with theme_id == this and theme_version_pinned == revoked_version, status=SCHEDULED
    for slot in list(store.session_slots.values()):
        if slot["theme_id"] == theme_id and \
                int(slot["theme_version_pinned"]) == revoked_version and \
                slot["schedule_status"] == "SCHEDULED":
            slot_service.cancel_slot(slot, "VENUE", user_id, role, trigger="content_revoked")
    from routes.themes import _theme_view
    return success_object(_theme_view(theme))
