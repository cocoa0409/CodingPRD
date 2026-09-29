"""The ice deck: flooding, the covering cycle and melt-out (PRD 3.6)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import serial
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from routes_venue import get_venue
from store import db, now_logical, ordered, stamp_new, touch

bp = Blueprint("ice", __name__)

ICE_STATUSES = ("BUILDING", "IN_SERVICE", "COVERED", "MELTING", "REMOVED")

# Transitions a caller may drive through the transition capability. The
# COVERED -> MELTING hop is system-only (cover-cycle limit), so it is absent.
ALLOWED_TRANSITIONS = {
    "BUILDING": ("IN_SERVICE",),
    "IN_SERVICE": ("COVERED", "MELTING"),
    "COVERED": ("IN_SERVICE",),
    "MELTING": ("REMOVED",),
    "REMOVED": (),
}


def get_sheet(sheet_id):
    sheet = db.ice_sheets.get(sheet_id)
    if sheet is None:
        raise ApiError("ERR_ICE_SHEET_NOT_FOUND")
    return sheet


def _dehum_floor_ok(required, applied):
    return calc.dec(applied) >= calc.MIN_DEHUM_FRACTION * calc.dec(required)


@bp.post("/venues/<venue_id>/ice-sheets")
def install_sheet(venue_id):
    v.auth(("ChangeoverSupervisor",))
    payload = v.body()
    profile_id = v.req_id(payload, "config_profile_id")
    applied = v.req_num(payload, "dehumidification_lph_applied", 0)
    thickness = v.opt_num(payload, "sheet_thickness_mm", 32, 18, 45)

    venue = get_venue(venue_id)
    profile = db.profiles.get(profile_id)
    if profile is None:
        raise ApiError("ERR_PROFILE_NOT_FOUND")

    # Ladder 12: single-sheet exclusivity.
    if calc.live_ice_sheet(venue["id"]) is not None:
        raise ApiError("ERR_ICE_SHEET_ALREADY_PRESENT")
    # Ladder 13: safety — the dehumidification floor.
    if not _dehum_floor_ok(profile["dehumidification_required_lph"], applied):
        raise ApiError("ERR_DEHUMIDIFICATION_INSUFFICIENT")
    # Ladder 17: referential scoping.
    if profile["venue_id"] != venue["id"]:
        raise ApiError("ERR_VENUE_SCOPE_MISMATCH")

    row = {
        "venue_id": venue["id"],
        "sheet_thickness_mm": thickness,
        "required_dehumidification_lph": profile["dehumidification_required_lph"],
        "dehumidification_lph_applied": applied,
        "status": "BUILDING",
        "cover_installed_at_utc": None,
        "cover_hours_accumulated": Decimal("0"),
        "cover_cycles": 0,
    }
    row["condensation_risk_score"] = calc.condensation_risk_score(row)
    stamp_new(row)
    db.ice_sheets[row["id"]] = row
    cascade.bump_venue(venue)
    return created(serial.ice_sheet(row))


@bp.get("/venues/<venue_id>/ice-sheets")
def list_sheets(venue_id):
    v.auth(v.ALL_ROLES)
    limit, offset = v.pagination()
    venue = get_venue(venue_id)
    status = v.filter_arg("status")
    matched = [s for s in db.ice_sheets.values() if s["venue_id"] == venue["id"]]
    if status is not None:
        matched = [s for s in matched if s["status"] == status]
    matched = ordered(matched)
    page, total = v.paginate(matched, limit, offset)
    return ok_list([serial.ice_sheet(s) for s in page], limit, offset, total)


def _ice_event_dependency(venue_id):
    """True when an ice-requiring live booking starts inside [now, now + 12h]."""
    now = now_logical()
    horizon = now + timedelta(minutes=calc.ICE_BUILD_MINUTES)
    for booking in db.bookings.values():
        if booking["venue_id"] != venue_id:
            continue
        if booking["status"] not in calc.LIVE_BOOKING_STATES:
            continue
        profile = db.profiles.get(booking["config_profile_id"])
        if profile is None or not profile["requires_ice"]:
            continue
        if now <= booking["event_start_utc"] <= horizon:
            return True
    return False


@bp.post("/ice-sheets/<sheet_id>/transition")
def transition_sheet(sheet_id):
    v.auth(("ChangeoverSupervisor",))
    payload = v.body()
    to_status = v.req_enum(payload, "to_status", ICE_STATUSES)
    revised = v.opt_num(payload, "dehumidification_lph_applied", None, 0)

    sheet = get_sheet(sheet_id)
    venue = db.venues.get(sheet["venue_id"])

    # Ladder 9: from-state legality.
    if to_status not in ALLOWED_TRANSITIONS.get(sheet["status"], ()):
        raise ApiError("ERR_INVALID_ICE_SHEET_STATE")

    applied = sheet["dehumidification_lph_applied"] if revised is None else revised

    # Ladder 13, in the pinned internal order: dehumidification floor, then the
    # condensation gate, then the melt-out event dependency.
    if sheet["status"] == "BUILDING" and to_status == "IN_SERVICE":
        if not _dehum_floor_ok(sheet["required_dehumidification_lph"], applied):
            raise ApiError("ERR_DEHUMIDIFICATION_INSUFFICIENT")

    if sheet["status"] == "IN_SERVICE" and to_status == "COVERED":
        candidate = dict(sheet)
        candidate["dehumidification_lph_applied"] = applied
        if calc.condensation_risk_score(candidate) >= calc.CONDENSATION_BLOCK_THRESHOLD:
            raise ApiError("ERR_CONDENSATION_RISK_TOO_HIGH")

    if sheet["status"] == "IN_SERVICE" and to_status == "MELTING":
        if _ice_event_dependency(sheet["venue_id"]):
            raise ApiError("ERR_ICE_EVENT_DEPENDENCY")

    sheet["dehumidification_lph_applied"] = applied

    if to_status == "COVERED":
        cascade.cover_ice_sheet(sheet)
    elif sheet["status"] == "COVERED" and to_status == "IN_SERVICE":
        if sheet["cover_installed_at_utc"] is not None:
            delta = calc.cover_hours_delta(sheet["cover_installed_at_utc"], now_logical())
            sheet["cover_hours_accumulated"] = calc.round_half_up(
                calc.dec(sheet["cover_hours_accumulated"]) + delta, 3)
        sheet["cover_installed_at_utc"] = None
        sheet["status"] = "IN_SERVICE"
    else:
        sheet["status"] = to_status

    sheet["condensation_risk_score"] = calc.condensation_risk_score(sheet)
    touch(sheet)
    if venue is not None:
        cascade.bump_venue(venue)
    return ok(serial.ice_sheet(sheet))
