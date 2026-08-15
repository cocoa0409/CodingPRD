"""Station routes: create/list/get, freeze/unfreeze, computed summary."""
from flask import Blueprint

import db
import services
from envelope import success
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_STATION_CODE,
)
from helpers import (
    body, bad, is_int, req_str, req_bool, paginate, STATION_CODE_RE,
)
from middleware import require_roles
from serializers import ser_station, ser_pump

bp = Blueprint("stations", __name__)

STATION_READ_ROLES = (
    "UtilityAdmin", "OperationsSupervisor", "OnCallOperator", "Operator",
    "MaintenancePlanner", "ComplianceOfficer", "CapitalProgramManager",
)
SUMMARY_ROLES = (
    "UtilityAdmin", "OperationsSupervisor", "OnCallOperator", "Operator",
    "MaintenancePlanner", "ComplianceOfficer",
)


def get_station_or_404(sid):
    s = db.stations.get(sid)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Station not found")
    return s


@bp.post("/stations")
def create_station():
    require_roles("UtilityAdmin")
    b = body()
    # business constraint (priority 13): format + uniqueness
    code = b.get("station_code")
    if code is not None:
        if not isinstance(code, str) or not STATION_CODE_RE.match(code):
            raise ApiError(
                ERR_DUPLICATE_STATION_CODE, 422,
                "station_code must match ^LS-[0-9]{4}$",
            )
        for s in db.stations.values():
            if s["station_code"] == code:
                raise ApiError(
                    ERR_DUPLICATE_STATION_CODE, 422,
                    "station_code %s already exists" % code,
                )
    # shape (priority 30)
    if code is None:
        bad("station_code is required")
    zone = req_str(b, "service_zone")
    cap = b.get("design_capacity_gpm")
    if not is_int(cap) or cap < 50:
        bad("design_capacity_gpm must be an integer >= 50")
    count = b.get("pump_count")
    if not is_int(count) or count < 2 or count > 8:
        bad("pump_count must be an integer between 2 and 8")
    backup = req_bool(b, "has_backup_generator")
    volume = b.get("wet_well_volume_gal")
    if not is_int(volume) or volume <= 0:
        bad("wet_well_volume_gal must be a positive integer")
    st = {
        "id": db.new_id(),
        "station_code": code,
        "service_zone": zone,
        "design_capacity_gpm": cap,
        "pump_count": count,
        "has_backup_generator": backup,
        "wet_well_volume_gal": volume,
        "operational_posture": "NORMAL",
        "firm_capacity_available_gpm": 0,
        "last_sso_occurred_at": None,
        "_frozen": False,
    }
    db.stamp(st)
    db.stations[st["id"]] = st
    return success(ser_station(st), 201)


@bp.get("/stations")
def list_stations():
    require_roles(*STATION_READ_ROLES)
    items = list(db.stations.values())
    zone = _q("service_zone")
    if zone is not None:
        items = [s for s in items if s["service_zone"] == zone]
    posture = _q("operational_posture")
    if posture is not None:
        items = [s for s in items if s["operational_posture"] == posture]
    page, meta = paginate(items)
    return success([ser_station(s) for s in page], 200, meta)


@bp.get("/stations/<sid>")
def get_station(sid):
    require_roles(*STATION_READ_ROLES)
    return success(ser_station(get_station_or_404(sid)))


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v is not None else None


# --------------------------------------------------------------------- freeze


@bp.post("/stations/<sid>/freeze")
def freeze_station(sid):
    require_roles("UtilityAdmin")
    st = get_station_or_404(sid)
    # Transition is NORMAL -> FROZEN only; preconditions: no active SSO,
    # no ISSUED/ACTIVE confined-space permit.
    if st["_frozen"] or st["operational_posture"] != "NORMAL":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a station in NORMAL posture can be frozen",
        )
    for p in db.confined_space_permits.values():
        if p["station_id"] == sid and p["status"] in ("ISSUED", "ACTIVE"):
            raise ApiError(
                ERR_INVALID_STATE, 409,
                "Station has a live confined-space permit; wind it down first",
            )
    # Cascade: scheduled cleanings and generator tests are cancelled.
    for c in db.wet_well_cleanings.values():
        if c["station_id"] == sid and c["status"] == "SCHEDULED":
            c["status"] = "CANCELLED"
            db.touch(c)
    for t in db.generator_tests.values():
        if t["station_id"] == sid and t["status"] == "SCHEDULED":
            t["status"] = "CANCELLED"
            db.touch(t)
    st["_frozen"] = True
    st["operational_posture"] = "FROZEN"
    db.touch(st)
    return success(ser_station(st))


@bp.post("/stations/<sid>/unfreeze")
def unfreeze_station(sid):
    require_roles("UtilityAdmin")
    st = get_station_or_404(sid)
    if not st["_frozen"]:
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a FROZEN station can be unfrozen",
        )
    st["_frozen"] = False
    # Posture recomputed from live child state; explicit version increment.
    services.sync_station(st, force_bump=True)
    return success(ser_station(st))


# --------------------------------------------------------------------- summary


@bp.get("/stations/<sid>/summary")
def station_summary(sid):
    require_roles(*SUMMARY_ROLES)
    st = get_station_or_404(sid)
    open_alarms = sum(
        1 for t in db.alarm_tickets.values()
        if t["station_id"] == sid and t["status"] == "OPEN"
    )
    overdue_cleanings = sum(
        1 for c in db.wet_well_cleanings.values()
        if c["station_id"] == sid and c["status"] == "OVERDUE"
    )
    overdue_tests = sum(
        1 for t in db.generator_tests.values()
        if t["station_id"] == sid and t["status"] == "OVERDUE"
    )
    rate = services.grease_accumulation_rate(sid)
    due = services.next_cleaning_due(sid)
    from helpers import num
    return success({
        "station_id": sid,
        "operational_posture": st["operational_posture"],
        "firm_capacity_available_gpm": st["firm_capacity_available_gpm"],
        "open_alarm_count": open_alarms,
        "overdue_cleaning_count": overdue_cleanings,
        "overdue_generator_test_count": overdue_tests,
        "grease_accumulation_rate_inches_per_day": num(rate) if rate is not None else None,
        "next_cleaning_due_at": db.fmt_dt(due) if due is not None else None,
        "last_sso_occurred_at": db.fmt_dt(st["last_sso_occurred_at"]),
    })
