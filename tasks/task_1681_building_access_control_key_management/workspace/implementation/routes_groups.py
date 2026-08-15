from flask import Blueprint, request

from db import STORE, CLOCK, next_seq, new_id, bump, is_int
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
                    ERR_PERSON_INACTIVE, ERR_CROSS_BUILDING_REFERENCE,
                    ERR_SCHEDULE_INVALID)
from middleware import authenticate, require_roles, body
from response import ok_object, paginate
from serializers import ser_access_group
from validators import get_or_404, req_str, opt_str, opt_str_list, req_hhmm
from services import DAYS

bp = Blueprint("groups", __name__)

STAFF_ROLES = ["SecurityAdmin", "SecurityOfficer", "FrontDesk"]


def _validate_days(days):
    """days_of_week must be a non-empty subset of MON..SUN."""
    if (not isinstance(days, list) or len(days) == 0
            or any(d not in DAYS for d in days)):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "days_of_week must be a non-empty subset of "
                       "MON..SUN")


def _resolve_members_exist(door_ids, person_ids):
    """Priority 3: body-supplied FK references must exist."""
    doors = [get_or_404("doors", did, "Door") for did in door_ids]
    persons = [get_or_404("persons", pid, "Person") for pid in person_ids]
    return doors, persons


def _check_members_active(persons):
    """Priority 6: every member person must be ACTIVE."""
    for p in persons:
        if p["status"] != "ACTIVE":
            raise ApiError(ERR_PERSON_INACTIVE, 422,
                           "Group member person is not ACTIVE")


def _check_members_same_building(building_id, doors, persons):
    """Priority 7: referenced doors/persons must be in the same building."""
    for d in doors:
        if d["building_id"] != building_id:
            raise ApiError(ERR_CROSS_BUILDING_REFERENCE, 422,
                           "door id belongs to a different building")
    for p in persons:
        if p["building_id"] != building_id:
            raise ApiError(ERR_CROSS_BUILDING_REFERENCE, 422,
                           "person id belongs to a different building")


@bp.route("/access-groups", methods=["POST"])
def create_group():
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin"])
    b = body()
    building_id = req_str(b, "building_id")
    name = req_str(b, "name")
    days = b.get("days_of_week")
    _validate_days(days)
    w_start = req_hhmm(b, "window_start_utc")
    w_end = req_hhmm(b, "window_end_utc")
    door_ids = opt_str_list(b, "door_ids", [])
    person_ids = opt_str_list(b, "person_ids", [])
    get_or_404("buildings", building_id, "Building")
    doors, persons = _resolve_members_exist(door_ids, person_ids)
    _check_members_active(persons)
    _check_members_same_building(building_id, doors, persons)
    if w_start == w_end:
        raise ApiError(ERR_SCHEDULE_INVALID, 422,
                       "window_start_utc must differ from window_end_utc")
    now = CLOCK.now()
    g = {
        "id": new_id(),
        "building_id": building_id,
        "name": name,
        "door_ids": door_ids,
        "person_ids": person_ids,
        "days_of_week": days,
        "window_start_utc": w_start,
        "window_end_utc": w_end,
        "seq": next_seq(building_id, "access_groups"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["access_groups"][g["id"]] = g
    return ok_object(ser_access_group(g), 201)


@bp.route("/access-groups", methods=["GET"])
def list_groups():
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    args = request.args
    rows = list(STORE["access_groups"].values())
    v = args.get("building_id")
    if v is not None:
        rows = [r for r in rows if r["building_id"] == v]
    v = args.get("door_id")
    if v is not None:
        rows = [r for r in rows if v in r["door_ids"]]
    v = args.get("person_id")
    if v is not None:
        rows = [r for r in rows if v in r["person_ids"]]
    return paginate(rows, args, ser_access_group)


@bp.route("/access-groups/<accessGroupId>", methods=["GET"])
def get_group(accessGroupId):
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    g = get_or_404("access_groups", accessGroupId, "AccessGroup")
    return ok_object(ser_access_group(g))


@bp.route("/access-groups/<accessGroupId>", methods=["PATCH"])
def patch_group(accessGroupId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin"])
    g = get_or_404("access_groups", accessGroupId, "AccessGroup")
    b = body()
    expected = b.get("expected_access_group_version")
    if not is_int(expected):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_access_group_version is required")
    # Structural validation of provided fields
    name = opt_str(b, "name")
    days = None
    if "days_of_week" in b and b["days_of_week"] is not None:
        _validate_days(b["days_of_week"])
        days = list(b["days_of_week"])
    w_start = None
    if b.get("window_start_utc") is not None:
        w_start = req_hhmm(b, "window_start_utc")
    w_end = None
    if b.get("window_end_utc") is not None:
        w_end = req_hhmm(b, "window_end_utc")
    door_ids = opt_str_list(b, "door_ids")
    person_ids = opt_str_list(b, "person_ids")
    # Body FK existence (priority 3)
    doors, persons = _resolve_members_exist(
        door_ids if door_ids is not None else [],
        person_ids if person_ids is not None else [])
    # OCC (priority 4)
    if expected != g["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_access_group_version does not match")
    # Business safety (priority 6), then referential (priority 7)
    _check_members_active(persons)
    _check_members_same_building(g["building_id"], doors, persons)
    # Temporal (priority 9): distinct window bounds after replacement
    eff_start = w_start if w_start is not None else g["window_start_utc"]
    eff_end = w_end if w_end is not None else g["window_end_utc"]
    if eff_start == eff_end:
        raise ApiError(ERR_SCHEDULE_INVALID, 422,
                       "window_start_utc must differ from window_end_utc")
    if name is not None:
        g["name"] = name
    if door_ids is not None:
        g["door_ids"] = door_ids
    if person_ids is not None:
        g["person_ids"] = person_ids
    if days is not None:
        g["days_of_week"] = days
    if w_start is not None:
        g["window_start_utc"] = w_start
    if w_end is not None:
        g["window_end_utc"] = w_end
    bump(g)
    return ok_object(ser_access_group(g))


@bp.route("/access-groups/<accessGroupId>", methods=["DELETE"])
def delete_group(accessGroupId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin"])
    g = get_or_404("access_groups", accessGroupId, "AccessGroup")
    del STORE["access_groups"][g["id"]]
    return "", 204
