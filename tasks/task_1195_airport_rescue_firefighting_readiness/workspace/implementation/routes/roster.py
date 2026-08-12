"""Firefighter roster and live-fire training records."""
from flask import Blueprint, request, g

from db import store, base_entity, touch, serialize, parse_date
from errors import (
    ApiError, ERR_FIREFIGHTER_NOT_FOUND, ERR_DUPLICATE_EMPLOYEE_NO,
    ERR_INVALID_STATE, ERR_FIREFIGHTER_NOT_ACTIVE, ERR_TRAINING_DATE_IN_FUTURE,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import (
    require, json_body, need_str, need_enum, need_date_str, ALL_ROLES,
)
from response import success, paginated
from services import calc

bp = Blueprint("roster", __name__)


def get_firefighter_or_404(fid):
    f = store.firefighters.get(fid)
    if f is None:
        raise ApiError(ERR_FIREFIGHTER_NOT_FOUND, 404, "Firefighter id does not exist")
    return f


def check_firefighter_ownership(fid):
    """Firefighter role may only address its own entity id (PRD §2.1)."""
    if g.user_role == "Firefighter" and g.user_id != fid:
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, 403,
                       "Firefighter role may only access its own record")


@bp.post("/arff/firefighters")
def create_firefighter():
    require(["ArffChief"])
    data = json_body()
    eno = need_str(data, "employee_no", nonempty=True)
    name = need_str(data, "full_name", nonempty=True)
    if any(f["employee_no"] == eno for f in store.firefighters.values()):
        raise ApiError(ERR_DUPLICATE_EMPLOYEE_NO, 409,
                       "Firefighter employee_no already in use")
    f = base_entity()
    f.update({
        "employee_no": eno,
        "full_name": name,
        "status": "ACTIVE",
        "last_live_fire_completed_on": None,
        "is_training_current": False,
        "is_deployable": False,
    })
    store.firefighters[f["id"]] = f
    calc.recompute_profile(bump="if_changed")
    return success(serialize(f), "object", 201)


@bp.get("/arff/firefighters")
def list_firefighters():
    require(ALL_ROLES)
    items = list(store.firefighters.values())
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return paginated(items)


@bp.get("/arff/firefighters/<fid>")
def get_firefighter(fid):
    require(ALL_ROLES)
    check_firefighter_ownership(fid)
    return success(serialize(get_firefighter_or_404(fid)), "object", 200)


@bp.get("/arff/firefighters/<fid>/training-records")
def list_training_records(fid):
    require(ALL_ROLES)
    check_firefighter_ownership(fid)
    get_firefighter_or_404(fid)
    items = [r for r in store.training_records.values() if r["firefighter_id"] == fid]
    return paginated(items)


@bp.post("/arff/firefighters/<fid>/suspend")
def suspend_firefighter(fid):
    require(["ArffChief"])
    f = get_firefighter_or_404(fid)
    if f["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Firefighter must be ACTIVE to suspend")
    f["status"] = "SUSPENDED"
    calc.refresh_firefighter(f)
    touch(f)
    calc.recompute_profile(bump="always")
    return success(serialize(f), "object", 200)


@bp.post("/arff/firefighters/<fid>/reactivate")
def reactivate_firefighter(fid):
    require(["ArffChief"])
    f = get_firefighter_or_404(fid)
    if f["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Firefighter must be SUSPENDED to reactivate")
    f["status"] = "ACTIVE"
    calc.refresh_firefighter(f)
    touch(f)
    calc.recompute_profile(bump="always")
    return success(serialize(f), "object", 200)


@bp.post("/arff/live-fire-training-records")
def create_training_record():
    require(["ArffChief"])
    data = json_body()
    raw_fid = data.get("firefighter_id")
    if isinstance(raw_fid, str) and raw_fid not in store.firefighters:
        raise ApiError(ERR_FIREFIGHTER_NOT_FOUND, 404, "Firefighter id does not exist")
    fid = need_str(data, "firefighter_id")
    completed = need_date_str(data, "completed_on")
    drill_type = need_enum(data, "drill_type", ["AIRCRAFT", "STRUCTURAL"])
    result = need_enum(data, "result", ["PASS", "FAIL"])
    f = store.firefighters[fid]
    if f["status"] != "ACTIVE":
        raise ApiError(ERR_FIREFIGHTER_NOT_ACTIVE, 409,
                       "Training record creation requires an ACTIVE firefighter")
    d = parse_date(completed)
    if d > store.clock.date():
        raise ApiError(ERR_TRAINING_DATE_IN_FUTURE, 422,
                       "completed_on must not be after the current logical date")
    r = base_entity()
    r.update({
        "firefighter_id": fid,
        "completed_on": completed,
        "drill_type": drill_type,
        "result": result,
        "_completed_date": d,
    })
    store.training_records[r["id"]] = r
    calc.refresh_firefighter(f)
    calc.recompute_profile(bump="always")
    return success(serialize(r), "object", 201)
