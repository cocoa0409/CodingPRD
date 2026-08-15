"""AbsenceReport + BackfillAssignment endpoints (PRD §3.6)."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_ABSENCE_INVALID_STATE, ERR_ABSENCE_NOT_OWN, ERR_ASSIGNMENT_INVALID_STATE,
    ERR_BACKFILL_INVALID_STATE, ERR_BACKFILL_NOT_OWN,
    ERR_COVERAGE_PLAN_FROZEN, ERR_COVERAGE_PLAN_NOT_PUBLISHED, ERR_STALE_VERSION,
    ERR_INVALID_DATE_RANGE, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    WEEKDAYS, as_date_str, as_int, as_str, bad_request, body_json, need,
    parse_date,
)

bp = Blueprint("absences", __name__)

COORD = {"SpecialEdCoordinator"}
REPORTERS = {"Teacher", "Paraprofessional"}
PARA = {"Paraprofessional"}
ANY = {"Any"}


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


@bp.post("/sped-staffing/absence-reports")
def create_absence():
    user_id, role = auth_context()
    require_role(role, REPORTERS)
    body = body_json(request)
    assignment_id = need(body, "assignment_id")
    assignment = svc.get_assignment(as_str(assignment_id, "assignment_id"))
    absence_date = as_date_str(need(body, "absence_date"), "absence_date")
    reason = as_str(need(body, "reason"), "reason")
    if ("expected_coverage_plan_version" not in body
            or body["expected_coverage_plan_version"] is None):
        bad_request("expected_coverage_plan_version is required")
    expected_version = as_int(body["expected_coverage_plan_version"],
                              "expected_coverage_plan_version")
    # Ownership: a paraprofessional reporter must own the assignment.
    if role == "Paraprofessional" and user_id != assignment["para_id"]:
        raise ApiError(ERR_ABSENCE_NOT_OWN, 403,
                       "paraprofessional may only report absences on own assignments")
    # State: the assignment must be ACTIVE.
    if assignment["status"] != "ACTIVE":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, 409,
                       "absence reporting requires an ACTIVE assignment")
    # Resolve the coverage plan for (assignment building, absence date).
    cp = svc.find_coverage_plan_for(assignment["building_id"], absence_date)
    if cp is None or cp["status"] in ("DRAFT",):
        raise ApiError(ERR_COVERAGE_PLAN_NOT_PUBLISHED, 409,
                       "no PUBLISHED coverage plan for the assignment building and date")
    if cp["status"] in ("LOCKED", "RECONCILED"):
        raise ApiError(ERR_COVERAGE_PLAN_FROZEN, 409,
                       "coverage plan is LOCKED/RECONCILED; mutation forbidden")
    # OCC on the resolved coverage plan version.
    if expected_version != cp["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_coverage_plan_version does not match")
    # Date coherence: weekday of absence must be in the assignment's days.
    d = parse_date(absence_date)
    if WEEKDAYS[d.weekday()] not in assignment["days_of_week"]:
        raise ApiError(ERR_INVALID_DATE_RANGE, 400,
                       "absence weekday is not one of the assignment's days_of_week")
    absence = {
        "plan_id": assignment["plan_id"],
        "assignment_id": assignment["id"],
        "coverage_plan_id": cp["id"],
        "absence_date": absence_date,
        "absence_minutes": (assignment["daily_end_minute"]
                            - assignment["daily_start_minute"]),
        "reason": reason,
        "reported_by_role": role,
        "declined_para_ids": [],
        "status": "REPORTED",
    }
    svc.stamp_new(absence)
    db.STORE["absences"][absence["id"]] = absence
    # Posture recomputes (derived); the coverage plan version increments by one.
    svc.touch(cp)
    return success(svc.ser_absence(absence), "object", 201)


@bp.get("/sped-staffing/absence-reports")
def list_absences():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    assignment_id = request.args.get("assignment_id")
    coverage_plan_id = request.args.get("coverage_plan_id")
    status = request.args.get("status")
    items = []
    for a in svc.sorted_records("absences"):
        if plan_id is not None and a["plan_id"] != plan_id:
            continue
        if assignment_id is not None and a["assignment_id"] != assignment_id:
            continue
        if coverage_plan_id is not None and a["coverage_plan_id"] != coverage_plan_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(svc.ser_absence(a))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/absence-reports/<absenceId>")
def get_absence(absenceId):
    _auth(ANY)
    absence = svc.get_absence(absenceId)
    return success(svc.ser_absence(absence), "object", 200)


def _cancel_offered_backfills(absence):
    for b in db.STORE["backfills"].values():
        if b["absence_id"] == absence["id"] and b["status"] == "OFFERED":
            b["status"] = "CANCELLED"
            svc.touch(b)


@bp.post("/sped-staffing/absence-reports/<absenceId>/escalate")
def escalate_absence(absenceId):
    _auth(COORD)
    absence = svc.get_absence(absenceId)
    if absence["status"] not in ("REPORTED", "BACKFILL_PENDING"):
        raise ApiError(ERR_ABSENCE_INVALID_STATE, 409,
                       "escalate requires absence REPORTED or BACKFILL_PENDING")
    _cancel_offered_backfills(absence)
    absence["status"] = "ESCALATED"
    svc.touch(absence)
    return success(svc.ser_absence(absence), "object", 200)


@bp.post("/sped-staffing/absence-reports/<absenceId>/cancel")
def cancel_absence(absenceId):
    _auth(COORD)
    absence = svc.get_absence(absenceId)
    if absence["status"] not in ("REPORTED", "BACKFILL_PENDING", "ESCALATED"):
        raise ApiError(ERR_ABSENCE_INVALID_STATE, 409,
                       "cancel requires a non-terminal absence state")
    _cancel_offered_backfills(absence)
    absence["status"] = "CANCELLED"
    svc.touch(absence)
    return success(svc.ser_absence(absence), "object", 200)


@bp.post("/sped-staffing/absence-reports/<absenceId>/backfill-offers")
def run_backfill_offers(absenceId):
    _auth(COORD)
    absence = svc.get_absence(absenceId)
    if absence["status"] not in ("REPORTED", "ESCALATED"):
        raise ApiError(ERR_ABSENCE_INVALID_STATE, 409,
                       "backfill selector runs from REPORTED or ESCALATED")
    plan = db.STORE["plans"][absence["plan_id"]]
    chosen = svc.run_backfill_selector(absence, plan)
    if chosen is None:
        # Empty-pool fallback: no offer; absence escalates.
        absence["status"] = "ESCALATED"
        svc.touch(absence)
        return success(svc.ser_absence(absence), "object", 201)
    absence["status"] = "BACKFILL_PENDING"
    svc.touch(absence)
    backfill = {
        "absence_id": absence["id"],
        "plan_id": absence["plan_id"],
        "substitute_para_id": chosen["id"],
        "coverage_minutes": absence["absence_minutes"],
        "status": "OFFERED",
    }
    svc.stamp_new(backfill)
    db.STORE["backfills"][backfill["id"]] = backfill
    return success(svc.ser_absence(absence), "object", 201)


# ---------------------------------------------------------------------------
# BackfillAssignment endpoints
# ---------------------------------------------------------------------------

@bp.get("/sped-staffing/backfill-assignments")
def list_backfills():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    absence_id = request.args.get("absence_id")
    substitute_para_id = request.args.get("substitute_para_id")
    status = request.args.get("status")
    items = []
    for b in svc.sorted_records("backfills"):
        if plan_id is not None and b["plan_id"] != plan_id:
            continue
        if absence_id is not None and b["absence_id"] != absence_id:
            continue
        if substitute_para_id is not None and b["substitute_para_id"] != substitute_para_id:
            continue
        if status is not None and b["status"] != status:
            continue
        items.append(svc.ser_backfill(b))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/backfill-assignments/<backfillId>")
def get_backfill(backfillId):
    _auth(ANY)
    b = svc.get_backfill(backfillId)
    return success(svc.ser_backfill(b), "object", 200)


def _own_or_403(user_id, backfill):
    if user_id != backfill["substitute_para_id"]:
        raise ApiError(ERR_BACKFILL_NOT_OWN, 403,
                       "only the offered substitute may answer this backfill")


@bp.post("/sped-staffing/backfill-assignments/<backfillId>/accept")
def accept_backfill(backfillId):
    user_id, role = auth_context()
    require_role(role, PARA)
    b = svc.get_backfill(backfillId)
    _own_or_403(user_id, b)
    if b["status"] != "OFFERED":
        raise ApiError(ERR_BACKFILL_INVALID_STATE, 409,
                       "accept requires backfill OFFERED")
    absence = db.STORE["absences"][b["absence_id"]]
    plan = db.STORE["plans"][b["plan_id"]]
    substitute = db.STORE["paras"][b["substitute_para_id"]]
    b["status"] = "ACCEPTED"
    svc.touch(b)
    absence["status"] = "COVERED"
    svc.touch(absence)
    svc.refresh_benefit_and_recost(substitute, plan)
    return success(svc.ser_backfill(b), "object", 200)


@bp.post("/sped-staffing/backfill-assignments/<backfillId>/decline")
def decline_backfill(backfillId):
    user_id, role = auth_context()
    require_role(role, PARA)
    b = svc.get_backfill(backfillId)
    _own_or_403(user_id, b)
    if b["status"] != "OFFERED":
        raise ApiError(ERR_BACKFILL_INVALID_STATE, 409,
                       "decline requires backfill OFFERED")
    absence = db.STORE["absences"][b["absence_id"]]
    b["status"] = "DECLINED"
    svc.touch(b)
    absence["declined_para_ids"].append(b["substitute_para_id"])
    svc.touch(absence)
    return success(svc.ser_backfill(b), "object", 200)


@bp.post("/sped-staffing/backfill-assignments/<backfillId>/cancel")
def cancel_backfill(backfillId):
    _auth(COORD)
    b = svc.get_backfill(backfillId)
    if b["status"] not in ("OFFERED", "ACCEPTED"):
        raise ApiError(ERR_BACKFILL_INVALID_STATE, 409,
                       "cancel requires backfill OFFERED or ACCEPTED")
    was_accepted = b["status"] == "ACCEPTED"
    b["status"] = "CANCELLED"
    svc.touch(b)
    if was_accepted:
        absence = db.STORE["absences"][b["absence_id"]]
        plan = db.STORE["plans"][b["plan_id"]]
        substitute = db.STORE["paras"][b["substitute_para_id"]]
        if absence["status"] == "COVERED":
            absence["status"] = "BACKFILL_PENDING"
            svc.touch(absence)
        svc.refresh_benefit_and_recost(substitute, plan)
    return success(svc.ser_backfill(b), "object", 200)
