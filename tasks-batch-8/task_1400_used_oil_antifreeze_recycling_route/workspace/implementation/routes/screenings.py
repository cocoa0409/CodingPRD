"""SampleScreening endpoints (PRD §3.4).

Screening thresholds (parts of the operating spec embodied in code):
  - halogen_ppm >= 1000 -> FAIL_HALOGEN (all tank kinds)
  - water_pct > 5.0 -> FAIL_WATER (USED_OIL and MIXED tanks)
  - ph_level outside 6.0..9.0 -> FAIL_PH (ANTIFREEZE and MIXED tanks;
    the pH constraint applies to antifreeze-bearing tanks only)
Result precedence when several checks fail: FAIL_HALOGEN, then FAIL_WATER,
then FAIL_PH.
"""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_SAMPLE_SCREENING_NOT_FOUND, ERR_STOP_NOT_SCREENING
from middleware import get_body, req_int, req_number, require_roles
from response import success_list, success_object
from services import cascades
from services.calc import round_half_up_1dp

bp = Blueprint("screenings", __name__)

READ_ROLES = ("RoutePlanner", "LabTech", "EHSOfficer", "Regulator")

HALOGEN_FAIL_PPM = 1000
WATER_FAIL_PCT = 5.0
PH_MIN = 6.0
PH_MAX = 9.0


def compute_result(tank_kind, halogen_ppm, water_pct, ph_level):
    if halogen_ppm >= HALOGEN_FAIL_PPM:
        return "FAIL_HALOGEN"
    if tank_kind in ("USED_OIL", "MIXED") and water_pct > WATER_FAIL_PCT:
        return "FAIL_WATER"
    if tank_kind in ("ANTIFREEZE", "MIXED") and (ph_level < PH_MIN or ph_level > PH_MAX):
        return "FAIL_PH"
    return "PASS"


@bp.post("/route-stops/<routeStopId>/sample-screenings")
@require_roles("LabTech")
def create_screening(routeStopId):
    stop = db.get("route_stops", routeStopId)
    if stop is None:
        raise ApiError("ERR_ROUTE_STOP_NOT_FOUND", "RouteStop id not found", 404)
    body = get_body()
    halogen_ppm = req_int(body, "halogen_ppm", minimum=0, maximum=100000)
    water_pct = round_half_up_1dp(req_number(body, "water_pct", minimum=0.0, maximum=100.0))
    ph_level = round_half_up_1dp(req_number(body, "ph_level", minimum=0.0, maximum=14.0))
    if stop["status"] != "SCREENING":
        raise ApiError(ERR_STOP_NOT_SCREENING, "Screening recording requires SCREENING", 409)

    tank = db.get("tanks", stop["tank_id"])
    site = db.get("tank_sites", stop["tank_site_id"])
    customer = cascades.customer_of_site(site)
    result = compute_result(tank["tank_kind"], halogen_ppm, water_pct, ph_level)

    screening = db.create_entity("sample_screenings", {
        "route_stop_id": stop["id"],
        "halogen_ppm": halogen_ppm,
        "water_pct": water_pct,
        "ph_level": ph_level,
        "result": result,
        "screened_by_user_id": request.user_id,
        "screening_recorded_at": db.now_iso(),
    })

    if result == "PASS":
        stop["_halogen_count_at_screen"] = customer["halogen_violation_count"]
        stop["status"] = "READY_TO_PUMP"
        db.touch(stop)
    elif result == "FAIL_HALOGEN":
        stop["status"] = "CANCELLED_HALOGEN"
        db.touch(stop)
        cascades.quarantine_tank(tank, cancel_stops=True)
        customer["halogen_violation_count"] += 1
        db.touch(customer)
    else:  # FAIL_WATER / FAIL_PH: recoverable; stop returns to SCHEDULED
        stop["status"] = "SCHEDULED"
        stop["_reschedule_note"] = f"Screening {result}; reschedule required"
        db.touch(stop)

    return success_object(db.serialize(screening), 201)


@bp.get("/sample-screenings/<screeningId>")
@require_roles(*READ_ROLES)
def get_screening(screeningId):
    screening = db.get("sample_screenings", screeningId)
    if screening is None:
        raise ApiError(ERR_SAMPLE_SCREENING_NOT_FOUND, "SampleScreening id not found", 404)
    return success_object(db.serialize(screening))


@bp.get("/sample-screenings")
@require_roles(*READ_ROLES)
def list_screenings():
    items = db.all_entities("sample_screenings")
    route_stop_id = request.args.get("route_stop_id")
    result = request.args.get("result")
    if route_stop_id is not None:
        items = [s for s in items if s["route_stop_id"] == route_stop_id]
    if result is not None:
        items = [s for s in items if s["result"] == result]
    return success_list([db.serialize(s) for s in db.sorted_created(items)])
