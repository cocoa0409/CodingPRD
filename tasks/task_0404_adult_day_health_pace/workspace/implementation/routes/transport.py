"""Transport leg endpoints. PRD §3.5."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import success, list_response
from services import common as c

bp = Blueprint("transport", __name__)

DIRECTIONS = {"PICKUP", "DROPOFF"}


def leg_view(l):
    return dict(l)


@bp.post("/pace/transport-legs")
@require_roles("IntakeCoordinator", "NurseStaff")
def create_leg():
    body = c.get_body()
    attendance_day_id = c.as_str(body, "attendance_day_id")
    direction = c.as_enum(body, "direction", DIRECTIONS)
    window_start = c.as_int(body, "window_start_min")
    window_end = c.as_int(body, "window_end_min")
    vehicle_id = c.as_str(body, "vehicle_id")
    day = c.find_or_404(db.attendance_days, attendance_day_id)

    # Window validity (priority 19): start in 0..1439, end > start, end <= 1440
    if not (0 <= window_start <= 1439):
        raise err("ERR_INVALID_WINDOW", "window_start_min out of range")
    if not (window_end > window_start and window_end <= 1440):
        raise err("ERR_INVALID_WINDOW", "window_end_min invalid")

    # Overlap: no overlap with another PLANNED leg on same vehicle + service_date
    # half-open [start, end); touching endpoints allowed (priority 20)
    svc_date = c.parse_iso(day["service_date"]).date()
    for other in db.transport_legs.values():
        if other["status"] != "PLANNED":
            continue
        if other["vehicle_id"] != vehicle_id:
            continue
        other_day = db.attendance_days.get(other["attendance_day_id"])
        if not other_day:
            continue
        if c.parse_iso(other_day["service_date"]).date() != svc_date:
            continue
        # overlap of [s1,e1) and [s2,e2): s1 < e2 and s2 < e1
        if window_start < other["window_end_min"] and other["window_start_min"] < window_end:
            raise err("ERR_TRANSPORT_OVERLAP", "Transport leg overlaps existing leg")

    leg = c.base_fields()
    leg.update({
        "attendance_day_id": attendance_day_id,
        "direction": direction,
        "window_start_min": window_start,
        "window_end_min": window_end,
        "vehicle_id": vehicle_id,
        "status": "PLANNED",
    })
    db.transport_legs[leg["id"]] = leg
    day["transport_leg_count"] = day["transport_leg_count"] + 1
    c.touch(day)
    return success(leg_view(leg), status=201)


@bp.get("/pace/transport-legs/<leg_id>")
@require_roles("ProgramAdmin", "IntakeCoordinator", "NurseStaff", "BillingSpecialist")
def get_leg(leg_id):
    leg = c.find_or_404(db.transport_legs, leg_id)
    return success(leg_view(leg))


@bp.get("/pace/transport-legs")
@require_roles("ProgramAdmin", "IntakeCoordinator", "NurseStaff", "BillingSpecialist")
def list_legs():
    limit, offset = c.get_pagination()
    items = list(db.transport_legs.values())
    for key in ("attendance_day_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([leg_view(l) for l in page], limit, offset, total)
