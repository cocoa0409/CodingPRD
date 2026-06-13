"""BookingSession endpoints (PRD §3.7)."""

from flask import Blueprint, request

import errors
from db import store, parse_dt, now_iso
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from response import ok
from decimal import Decimal

from services.calc import (compute_final_session_pay, round_half_up_cents,
                           FICA_EMPLOYEE_RATE, PLATFORM_FEE_PCT)
from services.common import touch
from services.ledger import recompute_w2_obligation
from services.lookup import get_session, get_booking, get_caregiver, get_family, sorted_by_created
from services.serialize import session_out
from services.temporal import caregiver_has_buffered_overlap

bp = Blueprint("sessions", __name__)

TERMINAL_SESSION = {"COMPLETED", "NO_SHOW", "CANCELLED"}


@bp.route("/marketplace/sessions/<sid>", methods=["GET"])
def get_one_session(sid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    s = get_session(sid)
    booking = get_booking(s["booking_id"])
    if auth.is_family and auth.user_id != booking["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only read its own sessions")
    if auth.is_caregiver and auth.user_id != s["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only read its own sessions")
    return ok(session_out(s), status=200)


@bp.route("/marketplace/sessions", methods=["GET"])
def list_sessions():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    caregiver_id = request.args.get("caregiver_id")
    status = request.args.get("status")

    items = list(store.sessions.values())
    if auth.is_caregiver:
        items = [s for s in items if s["caregiver_id"] == auth.user_id]
    if auth.is_family:
        fam_id = auth.user_id
        items = [s for s in items
                 if (store.bookings.get(s["booking_id"]) or {}).get("family_id") == fam_id]
    if booking_id is not None:
        items = [s for s in items if s["booking_id"] == booking_id]
    if caregiver_id is not None:
        items = [s for s in items if s["caregiver_id"] == caregiver_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([session_out(s) for s in page], status=200, pagination=meta)


def _all_siblings_terminal(booking_id):
    siblings = [s for s in store.sessions.values() if s["booking_id"] == booking_id]
    return all(s["status"] in TERMINAL_SESSION for s in siblings)


def _maybe_complete_booking(booking):
    """Bubble up to COMPLETED when every child session terminal with >=1 COMPLETED."""
    siblings = [s for s in store.sessions.values() if s["booking_id"] == booking["id"]]
    if not siblings:
        return
    if not all(s["status"] in TERMINAL_SESSION for s in siblings):
        return
    if not any(s["status"] == "COMPLETED" for s in siblings):
        return
    if booking["status"] != "IN_PROGRESS":
        return
    completed = [s for s in siblings if s["status"] == "COMPLETED"]
    final_pay = sum(s["gross_pay_cents"] for s in completed)
    booking["final_pay_cents"] = final_pay

    # Settle escrow: release the drift between the reserved estimate and what the
    # first session actually consumed, back to the family's available balance.
    # The booking is now done, so the entire reservation (estimated_pay_cents)
    # is released from escrow_reserved; available is re-derived from the wallet
    # identity. The drift (reserved - consumed) thus flows back to available.
    family = store.families.get(booking["family_id"])
    if family is not None:
        reserved = booking["estimated_pay_cents"]
        family["escrow_reserved_cents"] -= reserved
        if family["escrow_reserved_cents"] < 0:
            family["escrow_reserved_cents"] = 0
        avail = family["wallet_balance_cents"] - family["escrow_reserved_cents"]
        family["escrow_available_cents"] = avail if avail > 0 else 0
        touch(family)

    booking["status"] = "COMPLETED"
    touch(booking)


@bp.route("/marketplace/sessions/<sid>/clock-in", methods=["POST"])
def clock_in(sid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Caregiver"})
    s = get_session(sid)
    if auth.is_caregiver and auth.user_id != s["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only clock in its own sessions")

    booking = get_booking(s["booking_id"])

    # State (priority 4).
    if s["status"] != "SCHEDULED" or booking["status"] not in {"CONFIRMED", "IN_PROGRESS"}:
        raise err(errors.ERR_INVALID_STATE, "Session not clock-in-able")

    start_dt = parse_dt(s["window_start_iso"])
    end_dt = parse_dt(s["window_end_iso"])

    # Caregiver double-booking with travel buffer (priority 11).
    if caregiver_has_buffered_overlap(s["caregiver_id"], start_dt, end_dt,
                                      exclude_session_id=s["id"]):
        raise err(errors.ERR_CAREGIVER_DOUBLE_BOOKED, "Caregiver double-booked")

    s["status"] = "IN_PROGRESS"
    s["clock_in_at_iso"] = now_iso()
    touch(s)

    caregiver = get_caregiver(s["caregiver_id"])
    caregiver["availability_status"] = "BUSY"
    touch(caregiver)

    if booking["status"] == "CONFIRMED":
        booking["status"] = "IN_PROGRESS"
        touch(booking)

    return ok(session_out(s), status=200)


@bp.route("/marketplace/sessions/<sid>/clock-out", methods=["POST"])
def clock_out(sid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Caregiver"})
    s = get_session(sid)
    if auth.is_caregiver and auth.user_id != s["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only clock out its own sessions")

    if s["status"] != "IN_PROGRESS":
        raise err(errors.ERR_INVALID_STATE, "Session not IN_PROGRESS")

    booking = get_booking(s["booking_id"])
    family = get_family(booking["family_id"])
    caregiver = get_caregiver(s["caregiver_id"])

    clock_in_dt = parse_dt(s["clock_in_at_iso"])
    now = store.now()

    # Interval ordering (priority 13): clock-out strictly after clock-in.
    if not (now > clock_in_dt):
        raise err(errors.ERR_INVALID_INTERVAL, "Clock-out must be after clock-in")

    actual_hours, gross = compute_final_session_pay(
        clock_in_dt, now, booking["agreed_rate_cents"], family["num_children"],
        s["is_holiday"], booking["is_last_minute"],
    )

    s["clock_out_at_iso"] = now_iso()
    s["actual_hours"] = float(actual_hours)
    s["gross_pay_cents"] = gross
    s["status"] = "COMPLETED"
    touch(s)

    # Net of this session accrues to caregiver pending_earnings.
    fica = round_half_up_cents(Decimal(gross) * FICA_EMPLOYEE_RATE)
    fee = round_half_up_cents(Decimal(gross) * PLATFORM_FEE_PCT)
    net = gross - fica - fee
    caregiver["pending_earnings_cents"] += net
    caregiver["availability_status"] = "AVAILABLE"
    touch(caregiver)

    family["cash_wages_ytd_cents"] += gross
    recompute_w2_obligation(family)
    touch(family)

    _maybe_complete_booking(booking)

    return ok(session_out(s), status=200)


@bp.route("/marketplace/sessions/<sid>/no-show", methods=["POST"])
def no_show(sid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    s = get_session(sid)
    booking = get_booking(s["booking_id"])
    if auth.is_family and auth.user_id != booking["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only mark no-show on its own sessions")

    if s["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Session not SCHEDULED")

    end_dt = parse_dt(s["window_end_iso"])
    if not (store.now() >= end_dt):
        raise err(errors.ERR_INVALID_STATE, "Cannot mark no-show before window_end")

    s["status"] = "NO_SHOW"
    touch(s)
    _maybe_complete_booking(booking)
    return ok(session_out(s), status=200)
