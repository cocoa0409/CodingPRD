"""Session bookings and the minute ledger (PRD section 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from body import Body
from errors import invalid_request, invalid_state, raise_err
from gates import (P_AMP_NOT_ENDORSED, P_AMP_PROHIBITED, P_BODY, P_BODY_FK,
                   P_DAILY_CAP, P_HORIZON, P_INVOICE_PAST_DUE, P_LEAD_TIME,
                   P_OCC_PERMIT, P_OWNER, P_PATH, P_PERMIT_ACTIVE,
                   P_PERMIT_SUSPENDED, P_PITCH_CLOSED, P_QUIET_HOURS,
                   P_SEASON_MINUTES, P_SESSION_STARTED, P_SESSION_TOO_LONG,
                   P_SLOT_OVERLAP, P_STATE, require_version, resolve,
                   resolve_body_fk, run_gates)
from listing import listing
from middleware import (NOISE_INSPECTOR, PERFORMER, PERMIT_OFFICER,
                        require_owner, require_roles)
from response import ok_object
from services import calc, domain
from services.serializers import serialize
from utils import new_entity, touch, whole_minutes

bp = Blueprint("bookings", __name__, url_prefix="/busking")


@bp.post("/session-bookings")
def create_booking():
    user_id, role = require_roles([PERFORMER])
    raw = request.get_json(silent=True) or {}
    body = Body(raw)
    ctx = {}

    def check_fks():
        # Input-list order: permit_id then pitch_id.
        ctx["permit"] = resolve_body_fk("permits", raw, "permit_id")
        ctx["pitch"] = resolve_body_fk("pitches", raw, "pitch_id")

    def check_owner():
        if ctx["permit"] is not None:
            require_owner(role, user_id, ctx["permit"]["performer_id"])

    def check_body():
        body.req_id("permit_id")
        body.req_id("pitch_id")
        start_at = body.req_dt("start_at")
        end_at = body.req_dt("end_at")
        if not end_at > start_at:
            invalid_request("end_at must be strictly after start_at")
        ctx["start_at"] = start_at
        ctx["end_at"] = end_at
        ctx["expected"] = body.req_int("expected_permit_version")
        ctx["amplified"] = body.opt_bool("amplification_planned", False)
        ctx["duration"] = whole_minutes(start_at, end_at)
        ctx["zone"] = db.get("zones", ctx["pitch"]["zone_id"])

    def check_active():
        if ctx["permit"]["lifecycle_status"] != "ACTIVE":
            raise_err("ERR_PERMIT_NOT_ACTIVE", "The permit is not ACTIVE")

    def check_suspended():
        if ctx["permit"]["compliance_status"] == "SUSPENDED":
            raise_err("ERR_PERMIT_SUSPENDED", "The permit is suspended")

    def check_version():
        require_version(ctx["expected"], ctx["permit"]["version"], "ERR_STALE_PERMIT_VERSION")

    def check_amp_pitch():
        if ctx["amplified"] and not ctx["pitch"]["amplification_allowed"]:
            raise_err("ERR_AMPLIFICATION_PROHIBITED",
                      "Amplified acts may not occupy this pitch")

    def check_amp_permit():
        if ctx["amplified"] and not ctx["permit"]["amplification_endorsed"]:
            raise_err("ERR_AMPLIFICATION_NOT_ENDORSED",
                      "This permit carries no amplification endorsement")

    def check_quiet():
        if calc.violates_quiet_window(ctx["zone"], ctx["start_at"], ctx["end_at"]):
            raise_err("ERR_QUIET_HOURS_VIOLATION",
                      "The occupation falls inside the district's quiet window")

    def check_pitch_open():
        if ctx["pitch"]["availability_status"] != "OPEN":
            raise_err("ERR_PITCH_CLOSED", "The pitch is closed")

    def check_duration():
        if ctx["duration"] > ctx["pitch"]["max_session_minutes"]:
            raise_err("ERR_SESSION_TOO_LONG", "The occupation exceeds the pitch's ceiling")

    def check_lead_time():
        if ctx["start_at"] < db.now() + timedelta(minutes=calc.MIN_BOOKING_LEAD_MINUTES):
            raise_err("ERR_BOOKING_LEAD_TIME", "The session starts inside the lead-time window")

    def check_horizon():
        if ctx["start_at"] > db.now() + timedelta(days=calc.MAX_BOOKING_HORIZON_DAYS):
            raise_err("ERR_BOOKING_HORIZON_EXCEEDED",
                      "The session starts beyond the booking horizon")

    def check_overlap():
        if domain.has_slot_conflict(ctx["pitch"]["id"], ctx["start_at"], ctx["end_at"]):
            raise_err("ERR_PITCH_SLOT_OVERLAP",
                      "The occupation conflicts with an existing occupation on this pitch")

    def check_daily_cap():
        if (domain.daily_session_count(ctx["pitch"]["id"], ctx["start_at"])
                >= ctx["pitch"]["daily_session_cap"]):
            raise_err("ERR_PITCH_DAILY_CAP_REACHED",
                      "The pitch's daily session cap is already reached for that date")

    def check_past_due():
        if domain.has_past_due_invoice(ctx["permit"]):
            raise_err("ERR_INVOICE_PAST_DUE", "The permit carries a past-due invoice")

    def check_season_minutes():
        if ctx["permit"]["season_minutes_used"] + ctx["duration"] > calc.SEASON_MINUTES_CAP:
            raise_err("ERR_SEASON_MINUTE_CAP_EXCEEDED",
                      "The booking would exceed the season minute allowance")

    run_gates([
        (P_BODY_FK, check_fks),
        (P_OWNER, check_owner),
        (P_BODY, check_body),
        (P_PERMIT_ACTIVE, check_active),
        (P_PERMIT_SUSPENDED, check_suspended),
        (P_OCC_PERMIT, check_version),
        (P_AMP_PROHIBITED, check_amp_pitch),
        (P_AMP_NOT_ENDORSED, check_amp_permit),
        (P_QUIET_HOURS, check_quiet),
        (P_PITCH_CLOSED, check_pitch_open),
        (P_SESSION_TOO_LONG, check_duration),
        (P_LEAD_TIME, check_lead_time),
        (P_HORIZON, check_horizon),
        (P_SLOT_OVERLAP, check_overlap),
        (P_DAILY_CAP, check_daily_cap),
        (P_INVOICE_PAST_DUE, check_past_due),
        (P_SEASON_MINUTES, check_season_minutes),
    ])

    permit = ctx["permit"]
    booking = new_entity("bookings", {
        "permit_id": permit["id"],
        "pitch_id": ctx["pitch"]["id"],
        "lottery_entry_id": None,
        "relocated_from_pitch_id": None,
        "start_at": ctx["start_at"],
        "end_at": ctx["end_at"],
        "duration_minutes": ctx["duration"],
        "amplification_planned": ctx["amplified"],
        "origin": "DIRECT",
        "effective_noise_cap_db": calc.effective_noise_cap(
            ctx["zone"], ctx["pitch"], ctx["amplified"],
            permit["compliance_status"], ctx["start_at"]),
        "noise_violation_count": 0,
        "status": "RESERVED",
    })
    domain.add_minutes(permit, ctx["duration"])
    touch(permit)
    return ok_object(serialize(booking), status=201)


@bp.get("/session-bookings/<booking_id>")
def read_booking(booking_id):
    user_id, role = require_roles([PERMIT_OFFICER, PERFORMER, NOISE_INSPECTOR])
    ctx = {}

    def resolve_booking():
        ctx["booking"] = resolve("bookings", booking_id)
        ctx["permit"] = db.get("permits", ctx["booking"]["permit_id"])

    run_gates([
        (P_PATH, resolve_booking),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["permit"]["performer_id"])),
    ])
    return ok_object(serialize(ctx["booking"]))


@bp.get("/session-bookings")
def list_bookings():
    require_roles([PERMIT_OFFICER, PERFORMER, NOISE_INSPECTOR])
    return listing("bookings",
                   ["permit_id", "pitch_id", "lottery_entry_id",
                    "relocated_from_pitch_id", "status"],
                   request.args)


@bp.post("/session-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    user_id, role = require_roles([PERFORMER, PERMIT_OFFICER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def resolve_booking():
        ctx["booking"] = resolve("bookings", booking_id)
        ctx["permit"] = db.get("permits", ctx["booking"]["permit_id"])

    def check_body():
        ctx["reason"] = body.opt_str("reason")

    def check_state():
        if ctx["booking"]["status"] not in ("RESERVED", "RELOCATED"):
            invalid_state("Only a RESERVED or RELOCATED session can be released")

    def check_started():
        if not ctx["booking"]["start_at"] > db.now():
            raise_err("ERR_SESSION_ALREADY_STARTED", "The session has already begun")

    run_gates([
        (P_PATH, resolve_booking),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["permit"]["performer_id"])),
        (P_BODY, check_body),
        (P_STATE, check_state),
        (P_SESSION_STARTED, check_started),
    ])

    booking = ctx["booking"]
    permit = ctx["permit"]
    booking["status"] = "CANCELLED_BY_PERFORMER"
    touch(booking)
    domain.release_minutes(permit, booking["duration_minutes"])
    touch(permit)
    return ok_object(serialize(booking))
