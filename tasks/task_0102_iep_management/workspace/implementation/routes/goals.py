"""IEP goals + progress reports."""

from decimal import Decimal

from flask import Blueprint, request

from core.auth import require_role
from core.envelope import success_object, success_array
from core.errors import APIError
from core.pagination import parse_pagination, paginate
from core.store import (
    GOALS, PROGRESS_REPORTS, stamp_create, stamp_update, stamp_create_event,
)
from core.precision import round_half_up
from core.validation import (
    get_district, get_student, get_iep, get_goal, require_json_body, check_version,
)
from services.computations import recompute_goal_mastery
from services.serializers import goal_dto, progress_report_dto


bp = Blueprint("goals", __name__)


ALLOWED_DOMAINS = {"ACADEMIC", "COMMUNICATION", "MOTOR", "BEHAVIORAL", "FUNCTIONAL", "TRANSITION"}


def _validate_objectives(objectives):
    if not isinstance(objectives, list) or len(objectives) == 0:
        raise APIError("ERR_OBJECTIVE_WEIGHTS_INVALID", "objectives must be a non-empty array.")
    total_weight = Decimal(0)
    seen_ids = set()
    for obj in objectives:
        if not isinstance(obj, dict):
            raise APIError("ERR_OBJECTIVE_WEIGHTS_INVALID", "Each objective must be an object.")
        oid = obj.get("objective_id")
        if not isinstance(oid, str) or not oid:
            raise APIError("ERR_OBJECTIVE_WEIGHTS_INVALID", "objective_id is required.")
        if oid in seen_ids:
            raise APIError("ERR_OBJECTIVE_WEIGHTS_INVALID", "objective_id must be unique within a goal.")
        seen_ids.add(oid)
        w = obj.get("weight")
        try:
            w_dec = Decimal(str(w))
        except Exception:
            raise APIError("ERR_OBJECTIVE_WEIGHTS_INVALID", "weight must be numeric.")
        if w_dec <= 0 or w_dec > 1:
            raise APIError("ERR_OBJECTIVE_WEIGHTS_INVALID", "weight must be in (0, 1].")
        lpp = obj.get("latest_progress_percent", 0)
        if not isinstance(lpp, int) or isinstance(lpp, bool) or lpp < 0 or lpp > 100:
            # accept omitted (default 0)
            if "latest_progress_percent" in obj:
                raise APIError("ERR_OBJECTIVE_WEIGHTS_INVALID", "latest_progress_percent must be int 0..100.")
            obj["latest_progress_percent"] = 0
        total_weight += w_dec
    rounded_sum = round_half_up(total_weight, 2)
    if rounded_sum != 1.00:
        raise APIError("ERR_OBJECTIVE_WEIGHTS_INVALID", "Sum of objective weights must equal 1.00.")


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/goals", methods=["POST"])
def create_goal(district_id, student_id, iep_id):
    require_role(["SpecialEducationTeacher"])
    get_district(district_id)
    get_student(district_id, student_id)
    iep = get_iep(district_id, student_id, iep_id)
    body = require_json_body()

    domain = body.get("domain")
    description = body.get("description")
    objectives = body.get("objectives")

    if domain not in ALLOWED_DOMAINS:
        raise APIError("ERR_INVALID_REQUEST", "domain is invalid.")
    if not isinstance(description, str) or not description:
        raise APIError("ERR_INVALID_REQUEST", "description is required.")
    _validate_objectives(objectives)

    if iep.get("status") not in ("DRAFT", "AMENDMENT_PENDING"):
        raise APIError("ERR_IEP_NOT_DRAFT", "IEP must be DRAFT or AMENDMENT_PENDING.")

    # Normalize objectives (ensure default latest_progress_percent).
    norm_objs = []
    for obj in objectives:
        norm = {
            "objective_id": obj["objective_id"],
            "weight": float(obj["weight"]),
            "latest_progress_percent": int(obj.get("latest_progress_percent", 0)),
        }
        norm_objs.append(norm)

    goal = {
        "iep_id": iep_id,
        "student_id": student_id,
        "district_id": district_id,
        "domain": domain,
        "description": description,
        "objectives": norm_objs,
        "mastery_score": 0.00,
        "mastery_tier": "INSUFFICIENT_PROGRESS",
        "status": "PROPOSED",
    }
    stamp_create(goal)
    recompute_goal_mastery(goal)
    GOALS[goal["id"]] = goal
    return success_object(goal_dto(goal), http_status=201)


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/goals", methods=["GET"])
def list_goals(district_id, student_id, iep_id):
    user_id, role = require_role(["DistrictAdmin", "SpecialEducationTeacher", "RelatedServiceProvider",
                                  "SchoolPsychologist", "Parent"])
    student = get_student(district_id, student_id)
    if role == "Parent" and user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")
    get_iep(district_id, student_id, iep_id)
    limit, offset = parse_pagination()
    status_q = request.args.get("status")
    domain_q = request.args.get("domain")
    rows = [g for g in GOALS.values() if g.get("iep_id") == iep_id]
    if status_q:
        rows = [g for g in rows if g.get("status") == status_q]
    if domain_q:
        rows = [g for g in rows if g.get("domain") == domain_q]
    rows.sort(key=lambda r: r.get("created_at", ""))
    page, total = paginate([goal_dto(g) for g in rows], limit, offset)
    return success_array(page, limit=limit, offset=offset, total_count=total)


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/goals/<goal_id>/close", methods=["POST"])
def close_goal(district_id, student_id, iep_id, goal_id):
    require_role(["SpecialEducationTeacher"])
    get_district(district_id)
    get_student(district_id, student_id)
    iep = get_iep(district_id, student_id, iep_id)
    goal = get_goal(district_id, student_id, iep_id, goal_id)
    body = require_json_body()
    check_version(body.get("version"), goal.get("version", 1))

    if goal.get("status") != "ACTIVE":
        raise APIError("ERR_GOAL_NOT_ACTIVE", "Goal is not in ACTIVE.")
    if iep.get("status") != "ACTIVE":
        raise APIError("ERR_IEP_NOT_ACTIVE", "Parent IEP is not in ACTIVE.")

    disposition = body.get("disposition")
    if disposition not in ("MET", "NOT_MET"):
        raise APIError("ERR_INVALID_REQUEST", "disposition must be MET or NOT_MET.")

    if disposition == "MET":
        recompute_goal_mastery(goal)
        if goal.get("mastery_tier") != "MASTERED":
            raise APIError("ERR_GOAL_NOT_MASTERED", "Goal mastery_tier is not MASTERED.")
        goal["status"] = "MET"
    else:
        goal["status"] = "NOT_MET"
    stamp_update(goal)
    return success_object(goal_dto(goal))


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/goals/<goal_id>/progress-reports",
           methods=["POST"])
def create_progress_report(district_id, student_id, iep_id, goal_id):
    user_id, _ = require_role(["SpecialEducationTeacher"])
    district = get_district(district_id)
    get_student(district_id, student_id)
    iep = get_iep(district_id, student_id, iep_id)
    goal = get_goal(district_id, student_id, iep_id, goal_id)

    if goal.get("status") != "ACTIVE":
        raise APIError("ERR_GOAL_NOT_ACTIVE", "Goal is not in ACTIVE.")
    if iep.get("status") != "ACTIVE":
        raise APIError("ERR_IEP_NOT_ACTIVE", "Parent IEP is not in ACTIVE.")

    body = require_json_body()
    rpi = body.get("reporting_period_index")
    objective_progress = body.get("objective_progress")
    narrative = body.get("narrative")

    if not isinstance(rpi, int) or isinstance(rpi, bool) or rpi < 1:
        raise APIError("ERR_INVALID_REQUEST", "reporting_period_index must be a positive integer.")
    if not isinstance(objective_progress, list) or not objective_progress:
        raise APIError("ERR_INVALID_REQUEST", "objective_progress must be a non-empty array.")
    if not isinstance(narrative, str) or not (1 <= len(narrative) <= 2000):
        raise APIError("ERR_INVALID_REQUEST", "narrative length must be 1..2000.")

    # Objective set parity (priority 17).
    goal_obj_ids = {o["objective_id"] for o in goal.get("objectives", [])}
    report_obj_ids = []
    for entry in objective_progress:
        if not isinstance(entry, dict):
            raise APIError("ERR_PROGRESS_OBJECTIVE_SET_MISMATCH", "Each entry must be an object.")
        oid = entry.get("objective_id")
        prog = entry.get("progress_percent")
        if not isinstance(oid, str) or not oid:
            raise APIError("ERR_PROGRESS_OBJECTIVE_SET_MISMATCH", "objective_id required.")
        if not isinstance(prog, int) or isinstance(prog, bool) or prog < 0 or prog > 100:
            raise APIError("ERR_INVALID_REQUEST", "progress_percent must be int 0..100.")
        report_obj_ids.append(oid)
    if set(report_obj_ids) != goal_obj_ids or len(report_obj_ids) != len(goal_obj_ids):
        raise APIError(
            "ERR_PROGRESS_OBJECTIVE_SET_MISMATCH",
            "objective_progress must contain exactly the goal's objectives.",
        )

    # Uniqueness on (goal_id, reporting_period_index) — priority 18.
    for r in PROGRESS_REPORTS.values():
        if r.get("iep_goal_id") == goal_id and r.get("reporting_period_index") == rpi:
            raise APIError("ERR_DUPLICATE_PROGRESS_REPORT", "Duplicate (goal_id, period).")

    report = {
        "iep_goal_id": goal_id,
        "iep_id": iep_id,
        "student_id": student_id,
        "reporting_period_index": rpi,
        "reported_by_user_id": user_id,
        "objective_progress": list(objective_progress),
        "narrative": narrative,
    }
    stamp_create_event(report)
    PROGRESS_REPORTS[report["id"]] = report

    # Update goal objectives' latest_progress_percent.
    prog_map = {e["objective_id"]: int(e["progress_percent"]) for e in objective_progress}
    for obj in goal["objectives"]:
        if obj["objective_id"] in prog_map:
            obj["latest_progress_percent"] = prog_map[obj["objective_id"]]
    recompute_goal_mastery(goal)
    stamp_update(goal)

    return success_object(progress_report_dto(report), http_status=201)
