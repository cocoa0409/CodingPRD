"""Clock, School, Course, CourseLevel, Instructor, Equipment routes."""
from flask import Blueprint, request

import db
from clock import clock
from errors import (
    err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_STALE_VERSION, ERR_INVALID_STATE,
)
from middleware import get_identity, require_role
from response import success, success_list
from services import derive
from util import (
    parse_dt, require_str, require_int, require_enum, parse_pagination, paginate,
    touch,
)

bp = Blueprint("catalog", __name__)

DISCIPLINES = {"SURF", "SAIL", "WINDSURF", "KAYAK"}
EQUIPMENT_TYPES = {"BOARD", "SAIL_RIG", "KAYAK"}
REQUIRED_EQUIP_TYPES = {"BOARD", "SAIL_RIG", "KAYAK", "NONE"}
READ_ROLES = {"SchoolAdmin", "Instructor", "Student"}


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "request body must be a JSON object")
    return data


# ------------------------------ Clock -----------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    body = _body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise err(ERR_VALIDATION, "missing required field: to_iso8601")
    dt = parse_dt(body["to_iso8601"], "to_iso8601")
    with db.lock():
        clock.set(dt)
    iso = clock.get().strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{clock.get().microsecond // 1000:03d}Z"
    return success({"current_utc": iso}, 200)


# ------------------------------ School ----------------------------
@bp.route("/schools", methods=["POST"])
def create_school():
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    body = _body()
    name = require_str(body, "name")
    tz = body.get("timezone") or "UTC"
    if not isinstance(tz, str):
        raise err(ERR_VALIDATION, "timezone must be a string")
    with db.lock():
        now = db.now_iso()
        sid = db.new_id()
        rec = {
            "id": sid, "name": name, "timezone": tz,
            "storm_advisory_active": False,
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.schools[sid] = rec
        return success(derive.serialize_school(rec), 201)


@bp.route("/schools", methods=["GET"])
def list_schools():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.schools.values())
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_school(r) for r in page], limit, offset, total)


@bp.route("/schools/<sid>", methods=["GET"])
def get_school(sid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.schools.get(sid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "school not found")
    return success(derive.serialize_school(rec), 200)


@bp.route("/schools/<sid>/storm-advisory", methods=["POST"])
def storm_advisory(sid):
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    with db.lock():
        rec = db.schools.get(sid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "school not found")
        body = _body()
        if "active" not in body or not isinstance(body["active"], bool):
            raise err(ERR_VALIDATION, "active must be a boolean")
        if "expected_school_version" not in body or body["expected_school_version"] is None:
            raise err(ERR_VALIDATION, "missing required field: expected_school_version")
        expected = body["expected_school_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err(ERR_VALIDATION, "expected_school_version must be an integer")
        if expected != rec["version"]:
            raise err(ERR_STALE_VERSION, "school version mismatch")
        rec["storm_advisory_active"] = body["active"]
        touch(rec)
        return success(derive.serialize_school(rec), 200)


# ------------------------------ Course ----------------------------
@bp.route("/courses", methods=["POST"])
def create_course():
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    body = _body()
    school_id = require_str(body, "school_id")
    discipline = require_enum(body, "discipline", DISCIPLINES)
    title = require_str(body, "title")
    kind = require_enum(body, "kind", {"LESSON", "CERTIFICATION"})
    with db.lock():
        if school_id not in db.schools:
            raise err(ERR_NOT_FOUND, "school not found")
        now = db.now_iso()
        cid = db.new_id()
        rec = {
            "id": cid, "school_id": school_id, "discipline": discipline,
            "title": title, "kind": kind, "status": "ACTIVE",
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.courses[cid] = rec
        return success(derive.serialize_course(rec), 201)


@bp.route("/courses", methods=["GET"])
def list_courses():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    school_id = request.args.get("school_id")
    rows = [c for c in db.courses.values() if school_id is None or c["school_id"] == school_id]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_course(r) for r in page], limit, offset, total)


@bp.route("/courses/<cid>", methods=["GET"])
def get_course(cid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.courses.get(cid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "course not found")
    return success(derive.serialize_course(rec), 200)


# --------------------------- CourseLevel --------------------------
@bp.route("/levels", methods=["POST"])
def create_level():
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    body = _body()
    course_id = require_str(body, "course_id")
    rank = require_int(body, "rank", minimum=1)
    name = require_str(body, "name")
    max_spi = require_int(body, "max_students_per_instructor", minimum=1)
    base_price = require_int(body, "base_price_cents", minimum=0)
    min_age = require_int(body, "min_age", minimum=0)
    requires_swim = body.get("requires_swim_test")
    if requires_swim is None:
        requires_swim = True
    if not isinstance(requires_swim, bool):
        raise err(ERR_VALIDATION, "requires_swim_test must be a boolean")
    req_equip = require_enum(body, "required_equipment_type", REQUIRED_EQUIP_TYPES)
    with db.lock():
        course = db.courses.get(course_id)
        if course is None:
            raise err(ERR_NOT_FOUND, "course not found")
        # rank unique within course
        for l in db.levels.values():
            if l["course_id"] == course_id and l["rank"] == rank:
                raise err(ERR_VALIDATION, "rank must be unique within the course")
        now = db.now_iso()
        lid = db.new_id()
        rec = {
            "id": lid, "course_id": course_id, "school_id": course["school_id"],
            "rank": rank, "name": name, "max_students_per_instructor": max_spi,
            "base_price_cents": base_price, "min_age": min_age,
            "requires_swim_test": requires_swim, "required_equipment_type": req_equip,
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.levels[lid] = rec
        return success(derive.serialize_level(rec), 201)


@bp.route("/levels", methods=["GET"])
def list_levels():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    course_id = request.args.get("course_id")
    school_id = request.args.get("school_id")
    rows = [
        l for l in db.levels.values()
        if (course_id is None or l["course_id"] == course_id)
        and (school_id is None or l["school_id"] == school_id)
    ]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_level(r) for r in page], limit, offset, total)


@bp.route("/levels/<lid>", methods=["GET"])
def get_level(lid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.levels.get(lid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "level not found")
    return success(derive.serialize_level(rec), 200)


# ---------------------------- Instructor --------------------------
@bp.route("/instructors", methods=["POST"])
def create_instructor():
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    body = _body()
    school_id = require_str(body, "school_id")
    full_name = require_str(body, "full_name")
    disciplines = body.get("certified_disciplines")
    if not isinstance(disciplines, list) or any(d not in DISCIPLINES for d in disciplines):
        raise err(ERR_VALIDATION, "certified_disciplines must be a list of valid disciplines")
    with db.lock():
        if school_id not in db.schools:
            raise err(ERR_NOT_FOUND, "school not found")
        now = db.now_iso()
        iid = db.new_id()
        rec = {
            "id": iid, "school_id": school_id, "full_name": full_name,
            "certified_disciplines": list(disciplines), "status": "ACTIVE",
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.instructors[iid] = rec
        return success(derive.serialize_instructor(rec), 201)


@bp.route("/instructors", methods=["GET"])
def list_instructors():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    school_id = request.args.get("school_id")
    rows = [i for i in db.instructors.values() if school_id is None or i["school_id"] == school_id]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_instructor(r) for r in page], limit, offset, total)


@bp.route("/instructors/<iid>", methods=["GET"])
def get_instructor(iid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.instructors.get(iid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "instructor not found")
    return success(derive.serialize_instructor(rec), 200)


# --------------------------- EquipmentItem ------------------------
@bp.route("/equipment", methods=["POST"])
def create_equipment():
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    body = _body()
    school_id = require_str(body, "school_id")
    equipment_type = require_enum(body, "equipment_type", EQUIPMENT_TYPES)
    asset_tag = require_str(body, "asset_tag")
    hourly_rate = require_int(body, "hourly_rate_cents", minimum=0)
    deposit = require_int(body, "deposit_cents", minimum=0)
    with db.lock():
        if school_id not in db.schools:
            raise err(ERR_NOT_FOUND, "school not found")
        now = db.now_iso()
        eid = db.new_id()
        rec = {
            "id": eid, "school_id": school_id, "equipment_type": equipment_type,
            "asset_tag": asset_tag, "hourly_rate_cents": hourly_rate,
            "deposit_cents": deposit, "maintenance": False,
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.equipment[eid] = rec
        return success(derive.serialize_equipment(rec), 201)


@bp.route("/equipment", methods=["GET"])
def list_equipment():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    school_id = request.args.get("school_id")
    equipment_type = request.args.get("equipment_type")
    rows = [
        e for e in db.equipment.values()
        if (school_id is None or e["school_id"] == school_id)
        and (equipment_type is None or e["equipment_type"] == equipment_type)
    ]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_equipment(r) for r in page], limit, offset, total)


@bp.route("/equipment/<eid>", methods=["GET"])
def get_equipment(eid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.equipment.get(eid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "equipment not found")
    return success(derive.serialize_equipment(rec), 200)


@bp.route("/equipment/<eid>/maintenance", methods=["POST"])
def equipment_maintenance(eid):
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    with db.lock():
        rec = db.equipment.get(eid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "equipment not found")
        body = _body()
        if "in_maintenance" not in body or not isinstance(body["in_maintenance"], bool):
            raise err(ERR_VALIDATION, "in_maintenance must be a boolean")
        if "expected_equipment_version" not in body or body["expected_equipment_version"] is None:
            raise err(ERR_VALIDATION, "missing required field: expected_equipment_version")
        expected = body["expected_equipment_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err(ERR_VALIDATION, "expected_equipment_version must be an integer")
        if expected != rec["version"]:
            raise err(ERR_STALE_VERSION, "equipment version mismatch")
        want = body["in_maintenance"]
        cur = derive.equipment_status(rec)
        if want:
            # MAINTENANCE only from AVAILABLE (PRD §3.2)
            if cur != "AVAILABLE":
                raise err(ERR_INVALID_STATE, "equipment must be AVAILABLE to enter maintenance")
            rec["maintenance"] = True
        else:
            rec["maintenance"] = False
        touch(rec)
        return success(derive.serialize_equipment(rec), 200)
