"""ServicePlacement endpoints."""

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_GUARDIAN_MISMATCH,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_PLACEMENT_STATE,
    ERR_PLACEMENT_PERIOD_OVERLAP,
)
from middleware import require_roles, ALL_ROLES, check_guardian_ownership
from response import success_object, success_list
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_enum,
    get_or_404,
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_created,
    parse_date,
    occupied_count,
    serialize_placement,
    _MODEL_FIELD,
)
from services import domain

bp = Blueprint("placements", __name__)

SERVICE_MODELS = {"PULL_OUT", "CLUSTER", "ACCELERATION"}

# statuses that occupy a service period for the per-student overlap rule
_PERIOD_ACTIVE_STATUSES = {"OFFERED", "ACTIVE", "WAITLISTED"}


@bp.route("/gifted/cases/<cid>/placements", methods=["POST"])
def create_placement(cid):
    require_roles("GiftedCoordinator")
    case = get_or_404(db.gifted_cases, cid, "case")
    body = get_json_body()
    require_fields(body, ["site_id", "service_model", "start_on"])
    site_id = require_string(body, "site_id")
    service_model = require_enum(body, "service_model", SERVICE_MODELS)
    start_raw = body["start_on"]
    start_d = parse_date(start_raw, "start_on")

    # site FK existence (priority 4 per PRD §3.6)
    get_or_404(db.school_sites, site_id, "school site")

    # case state gate (priority 7)
    if case["status"] != "IDENTIFIED":
        raise ApiError(ERR_INVALID_CASE_STATE, "placement offer requires case IDENTIFIED", 409)

    # per-student period overlap (priority 11); open-ended (end_on null) = infinity
    student_id = case["student_id"]
    for p in db.service_placements.values():
        if p["student_id"] != student_id:
            continue
        if p["status"] not in _PERIOD_ACTIVE_STATUSES:
            continue
        p_start = parse_date(p["start_on"], "start_on")
        p_end = parse_date(p["end_on"], "end_on") if p.get("end_on") else None
        # overlap of [start, inf) with [p_start, p_end or inf)
        if p_end is None:
            raise ApiError(ERR_PLACEMENT_PERIOD_OVERLAP, "student holds an open-ended placement", 409)
        if start_d <= p_end:
            raise ApiError(ERR_PLACEMENT_PERIOD_OVERLAP, "service period overlaps an existing placement", 409)

    today = db.today()
    ts = now_iso()
    placement = {
        "id": new_id(),
        "case_id": cid,
        "student_id": student_id,
        "site_id": site_id,
        "service_model": service_model,
        "start_on": start_raw,
        "end_on": None,
        "status": "OFFERED",
        "offered_on": today.isoformat(),
        "accept_by": (today + timedelta(days=30)).isoformat(),
        "waitlisted_at": None,
        "is_on_probation": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.service_placements[placement["id"]] = placement
    return success_object(serialize_placement(placement), 201)


@bp.route("/gifted/placements/<pid>", methods=["GET"])
def get_placement(pid):
    require_roles(*ALL_ROLES)
    placement = get_or_404(db.service_placements, pid, "placement")
    return success_object(serialize_placement(placement), 200)


@bp.route("/gifted/cases/<cid>/placements", methods=["GET"])
def list_case_placements(cid):
    require_roles(*ALL_ROLES)
    get_or_404(db.gifted_cases, cid, "case")
    items = [p for p in db.service_placements.values() if p["case_id"] == cid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_placement(p) for p in page], total, limit, offset)


@bp.route("/gifted/placements/<pid>/accept", methods=["POST"])
def accept_placement(pid):
    user_id, role = require_roles("ParentGuardian")
    placement = get_or_404(db.service_placements, pid, "placement")
    student = db.students.get(placement["student_id"])

    # guardian ownership (priority 3)
    if student is None:
        get_or_404(db.students, placement["student_id"], "student")
    check_guardian_ownership(user_id, student)

    # state gate (priority 7)
    if placement["status"] != "OFFERED":
        raise ApiError(ERR_INVALID_PLACEMENT_STATE, "accept requires placement status OFFERED", 409)

    site = db.school_sites.get(placement["site_id"])
    cap_field, _ = _MODEL_FIELD[placement["service_model"]]
    capacity = site[cap_field] if site else 0
    occupied = occupied_count(placement["site_id"], placement["service_model"])

    if occupied < capacity:
        placement["status"] = "ACTIVE"
    else:
        placement["status"] = "WAITLISTED"
        placement["waitlisted_at"] = now_iso()
    domain.touch(placement)
    return success_object(serialize_placement(placement), 200)


@bp.route("/gifted/placements/<pid>/decline", methods=["POST"])
def decline_placement(pid):
    user_id, role = require_roles("ParentGuardian")
    placement = get_or_404(db.service_placements, pid, "placement")
    student = get_or_404(db.students, placement["student_id"], "student")
    check_guardian_ownership(user_id, student)

    if placement["status"] not in {"OFFERED", "WAITLISTED"}:
        raise ApiError(ERR_INVALID_PLACEMENT_STATE, "decline requires placement OFFERED or WAITLISTED", 409)

    placement["status"] = "DECLINED"
    placement["waitlisted_at"] = None
    domain.touch(placement)
    return success_object(serialize_placement(placement), 200)


@bp.route("/gifted/placements/<pid>/withdraw", methods=["POST"])
def withdraw_placement(pid):
    user_id, role = require_roles("GiftedCoordinator", "ParentGuardian")
    placement = get_or_404(db.service_placements, pid, "placement")
    student = get_or_404(db.students, placement["student_id"], "student")

    # guardian ownership (priority 3) — coordinators always allowed
    if role == "ParentGuardian":
        check_guardian_ownership(user_id, student)

    if placement["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_PLACEMENT_STATE, "withdraw requires placement status ACTIVE", 409)

    domain.run_exit_cascade(placement)
    return success_object(serialize_placement(placement), 200)
