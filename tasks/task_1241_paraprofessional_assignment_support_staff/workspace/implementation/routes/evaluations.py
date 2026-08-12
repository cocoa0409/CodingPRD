"""Evaluation endpoints (PRD §3.8): author, submit, countersign, acknowledge,
dispute, resolve — with segregation of duties."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_EVALUATION_INVALID_STATE, ERR_EVALUATION_NOT_OWN,
    ERR_EVALUATION_SELF_COUNTERSIGN, ERR_INVALID_DATE_RANGE, ERR_PLAN_NOT_ACTIVE,
    ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import as_date_str, as_int, as_str, bad_request, body_json, need, parse_date

bp = Blueprint("evaluations", __name__)

TEACHER = {"Teacher"}
ADMIN_BLDG = {"BuildingAdministrator"}
PARA = {"Paraprofessional"}
ANY = {"Any"}


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


@bp.post("/sped-staffing/evaluations")
def create_evaluation():
    user_id, role = auth_context()
    require_role(role, TEACHER)
    body = body_json(request)
    plan_id = need(body, "plan_id")
    plan = svc.get_plan(as_str(plan_id, "plan_id"))
    para_id = need(body, "para_id")
    para = svc.get_para(as_str(para_id, "para_id"))
    period_start = as_date_str(need(body, "period_start"), "period_start")
    period_end = as_date_str(need(body, "period_end"), "period_end")
    professionalism = as_int(need(body, "professionalism_score"),
                             "professionalism_score")
    instructional = as_int(need(body, "instructional_support_score"),
                           "instructional_support_score")
    if not (1 <= professionalism <= 5):
        bad_request("professionalism_score must be within 1..5")
    if not (1 <= instructional <= 5):
        bad_request("instructional_support_score must be within 1..5")
    comments = as_str(need(body, "comments"), "comments")
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "evaluation authoring requires plan ACTIVE")
    if parse_date(period_end) < parse_date(period_start):
        raise ApiError(ERR_INVALID_DATE_RANGE, 400,
                       "period_end must not precede period_start")
    evaluation = {
        "plan_id": plan["id"],
        "para_id": para["id"],
        "period_start": period_start,
        "period_end": period_end,
        "professionalism_score": professionalism,
        "instructional_support_score": instructional,
        "comments": comments,
        "created_by_user_id": user_id,
        "countersigned_by_user_id": None,
        "resolution_note": None,
        "status": "DRAFT",
    }
    svc.stamp_new(evaluation)
    db.STORE["evaluations"][evaluation["id"]] = evaluation
    return success(svc.ser_evaluation(evaluation), "object", 201)


@bp.get("/sped-staffing/evaluations")
def list_evaluations():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    para_id = request.args.get("para_id")
    status = request.args.get("status")
    items = []
    for e in svc.sorted_records("evaluations"):
        if plan_id is not None and e["plan_id"] != plan_id:
            continue
        if para_id is not None and e["para_id"] != para_id:
            continue
        if status is not None and e["status"] != status:
            continue
        items.append(svc.ser_evaluation(e))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/evaluations/<evaluationId>")
def get_evaluation(evaluationId):
    _auth(ANY)
    e = svc.get_evaluation(evaluationId)
    return success(svc.ser_evaluation(e), "object", 200)


@bp.post("/sped-staffing/evaluations/<evaluationId>/submit")
def submit_evaluation(evaluationId):
    user_id, role = auth_context()
    require_role(role, TEACHER)
    e = svc.get_evaluation(evaluationId)
    if e["created_by_user_id"] != user_id:
        raise ApiError(ERR_EVALUATION_NOT_OWN, 403,
                       "only the authoring teacher may submit this evaluation")
    if e["status"] != "DRAFT":
        raise ApiError(ERR_EVALUATION_INVALID_STATE, 409,
                       "submit requires evaluation DRAFT")
    e["status"] = "SUBMITTED"
    svc.touch(e)
    return success(svc.ser_evaluation(e), "object", 200)


@bp.post("/sped-staffing/evaluations/<evaluationId>/countersign")
def countersign_evaluation(evaluationId):
    user_id, role = auth_context()
    require_role(role, ADMIN_BLDG)
    e = svc.get_evaluation(evaluationId)
    if e["status"] != "SUBMITTED":
        raise ApiError(ERR_EVALUATION_INVALID_STATE, 409,
                       "countersign requires evaluation SUBMITTED")
    # Segregation of duties: countersigner must differ from the author.
    if user_id == e["created_by_user_id"]:
        raise ApiError(ERR_EVALUATION_SELF_COUNTERSIGN, 403,
                       "countersigning administrator must differ from the author")
    e["countersigned_by_user_id"] = user_id
    e["status"] = "COUNTERSIGNED"
    svc.touch(e)
    return success(svc.ser_evaluation(e), "object", 200)


@bp.post("/sped-staffing/evaluations/<evaluationId>/acknowledge")
def acknowledge_evaluation(evaluationId):
    user_id, role = auth_context()
    require_role(role, PARA)
    e = svc.get_evaluation(evaluationId)
    if e["para_id"] != user_id:
        raise ApiError(ERR_EVALUATION_NOT_OWN, 403,
                       "only the evaluated para may acknowledge this evaluation")
    if e["status"] != "COUNTERSIGNED":
        raise ApiError(ERR_EVALUATION_INVALID_STATE, 409,
                       "acknowledge requires evaluation COUNTERSIGNED")
    e["status"] = "ACKNOWLEDGED"
    svc.touch(e)
    return success(svc.ser_evaluation(e), "object", 200)


@bp.post("/sped-staffing/evaluations/<evaluationId>/dispute")
def dispute_evaluation(evaluationId):
    user_id, role = auth_context()
    require_role(role, PARA)
    e = svc.get_evaluation(evaluationId)
    if e["para_id"] != user_id:
        raise ApiError(ERR_EVALUATION_NOT_OWN, 403,
                       "only the evaluated para may dispute this evaluation")
    if e["status"] != "COUNTERSIGNED":
        raise ApiError(ERR_EVALUATION_INVALID_STATE, 409,
                       "dispute requires evaluation COUNTERSIGNED")
    e["status"] = "DISPUTED"
    svc.touch(e)
    return success(svc.ser_evaluation(e), "object", 200)


@bp.post("/sped-staffing/evaluations/<evaluationId>/resolve")
def resolve_evaluation(evaluationId):
    user_id, role = auth_context()
    require_role(role, ADMIN_BLDG)
    e = svc.get_evaluation(evaluationId)
    body = body_json(request)
    resolution_note = as_str(need(body, "resolution_note"), "resolution_note")
    if e["status"] != "DISPUTED":
        raise ApiError(ERR_EVALUATION_INVALID_STATE, 409,
                       "resolve requires evaluation DISPUTED")
    e["resolution_note"] = resolution_note
    e["status"] = "RESOLVED"
    svc.touch(e)
    return success(svc.ser_evaluation(e), "object", 200)
