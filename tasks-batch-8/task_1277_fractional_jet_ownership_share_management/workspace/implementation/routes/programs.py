"""Program endpoints and posture state machine (PRD 2.9)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok
from services.core import new_common, program_view, touch
from util import as_int, as_list, as_str, body, required

bp = Blueprint("programs", __name__)


def _get_program(pid):
    p = db.programs.get(pid)
    if not p:
        raise ApiError("ERR_NOT_FOUND", 404, "Program not found")
    return p


@bp.route("/programs", methods=["POST"])
def create_program():
    require_roles("ProgramAdmin")
    data = body()
    program_code = as_str(required(data, "program_code"), "program_code")
    currency = as_str(required(data, "currency"), "currency")
    cym = as_int(required(data, "contract_year_start_month"), "contract_year_start_month")
    if cym < 1 or cym > 12:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "contract_year_start_month must be in 1..12")
    peak = as_list(required(data, "peak_day_calendar"), "peak_day_calendar")
    for d in peak:
        as_str(d, "peak_day_calendar[]")
    if len(set(peak)) != len(peak):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "peak_day_calendar dates must be distinct")

    rec = new_common()
    rec.update({
        "program_code": program_code,
        "currency": currency,
        "contract_year_start_month": cym,
        "peak_day_calendar": list(peak),
        "program_posture": "ACTIVE",
    })
    db.programs[rec["id"]] = rec
    return ok(program_view(rec), status=201)


@bp.route("/programs/<pid>", methods=["GET"])
def get_program(pid):
    require_roles(*ALL_ROLES)
    return ok(program_view(_get_program(pid)))


@bp.route("/programs/<pid>/suspend", methods=["POST"])
def suspend_program(pid):
    require_roles("ProgramAdmin")
    p = _get_program(pid)
    if p["program_posture"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Program is CLOSED")
    if p["program_posture"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Program must be ACTIVE to suspend")
    p["program_posture"] = "SUSPENDED"
    touch(p)
    return ok(program_view(p))


@bp.route("/programs/<pid>/resume", methods=["POST"])
def resume_program(pid):
    require_roles("ProgramAdmin")
    p = _get_program(pid)
    if p["program_posture"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Program is CLOSED")
    if p["program_posture"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Program must be SUSPENDED to resume")
    # Precondition: no more than half of IN_SERVICE aircraft under IN_PROGRESS
    # maintenance.
    in_service = [
        a for a in db.aircraft.values()
        if a["program_id"] == p["id"] and a["aircraft_status"] == "IN_SERVICE"
    ]
    in_prog_tails = {
        m["aircraft_id"] for m in db.maintenance_events.values()
        if m["event_status"] == "IN_PROGRESS"
    }
    afflicted = [a for a in in_service if a["id"] in in_prog_tails]
    if len(afflicted) * 2 > len(in_service):
        raise ApiError(
            "ERR_INVALID_STATE", 409,
            "More than half of IN_SERVICE aircraft have IN_PROGRESS maintenance",
        )
    p["program_posture"] = "ACTIVE"
    touch(p)
    return ok(program_view(p))


@bp.route("/programs/<pid>/wind-down", methods=["POST"])
def wind_down_program(pid):
    require_roles("ProgramAdmin")
    p = _get_program(pid)
    if p["program_posture"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Program is CLOSED")
    if p["program_posture"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Program must be ACTIVE or SUSPENDED to wind down")
    p["program_posture"] = "WINDING_DOWN"
    touch(p)
    # Cascades: REQUESTED bookings -> EXPIRED; LISTED listings -> EXPIRED.
    program_class_ids = {
        c["id"] for c in db.aircraft_classes.values()
        if c["program_id"] == p["id"]
    }
    program_share_ids = {
        s["id"] for s in db.shares.values() if s["class_id"] in program_class_ids
    }
    for b in db.bookings.values():
        if b["share_id"] in program_share_ids and b["booking_status"] == "REQUESTED":
            b["booking_status"] = "EXPIRED"
            touch(b)
    for t in db.transfer_listings.values():
        if t["share_id"] in program_share_ids and t["listing_status"] == "LISTED":
            t["listing_status"] = "EXPIRED"
            touch(t)
            share = db.shares.get(t["share_id"])
            if share and share["share_status"] == "LISTED":
                share["share_status"] = "ACTIVE"
                touch(share)
    return ok(program_view(p))


@bp.route("/programs/<pid>/close", methods=["POST"])
def close_program(pid):
    require_roles("ProgramAdmin")
    p = _get_program(pid)
    if p["program_posture"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Program is CLOSED")
    if p["program_posture"] != "WINDING_DOWN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Program must be WINDING_DOWN to close")
    program_class_ids = {
        c["id"] for c in db.aircraft_classes.values()
        if c["program_id"] == p["id"]
    }
    program_shares = [
        s for s in db.shares.values() if s["class_id"] in program_class_ids
    ]
    program_share_ids = {s["id"] for s in program_shares}
    if any(s["share_status"] in ("ACTIVE", "LISTED") for s in program_shares):
        raise ApiError("ERR_PROGRAM_NOT_CLOSABLE", 409,
                       "Shares still ACTIVE or LISTED")
    if any(
        x["share_id"] in program_share_ids
        and x["exit_status"] in ("SUBMITTED", "VALUED", "APPROVED")
        for x in db.exit_requests.values()
    ):
        raise ApiError("ERR_PROGRAM_NOT_CLOSABLE", 409,
                       "Exit requests still open")
    program_owner_ids = {
        o["id"] for o in db.owners.values() if o["program_id"] == p["id"]
    }
    if any(
        inv["owner_id"] in program_owner_ids
        and inv["invoice_status"] in ("OPEN", "ISSUED", "PAST_DUE", "DISPUTED")
        for inv in db.invoices.values()
    ):
        raise ApiError("ERR_PROGRAM_NOT_CLOSABLE", 409,
                       "Invoices still open")
    p["program_posture"] = "CLOSED"
    touch(p)
    for o in db.owners.values():
        if o["program_id"] == p["id"] and o["owner_standing"] != "EXITED":
            o["owner_standing"] = "EXITED"
            touch(o)
    return ok(program_view(p))
