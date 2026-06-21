"""PipCase routes."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_VALIDATION,
)
from middleware import get_caller, require_role
from response import ok_object, ok_array
from services.common import (
    touch, public, paginate, get_body, require_fields, as_int, as_number,
)

bp = Blueprint("pip_cases", __name__)


def pip_view(p):
    return public(p)


@bp.route("/reviews/<rid>/pip-cases", methods=["GET"])
def list_review_pips(rid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "Manager"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    items = [p for p in db.pip_cases.values() if p["review_id"] == rid]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([pip_view(p) for p in page], limit, offset, total, has_more)


@bp.route("/pip-cases", methods=["GET"])
def list_pips():
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner"})
    employee_id = request.args.get("employee_id")
    status = request.args.get("status")
    items = [
        p for p in db.pip_cases.values()
        if (employee_id is None or p["employee_id"] == employee_id)
        and (status is None or p["status"] == status)
    ]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([pip_view(p) for p in page], limit, offset, total, has_more)


@bp.route("/pip-cases/<pid>", methods=["GET"])
def get_pip(pid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "Manager"})
    p = db.pip_cases.get(pid)
    if not p:
        raise err(ERR_NOT_FOUND, "PIP case not found")
    return ok_object(pip_view(p))


@bp.route("/pip-cases/<pid>/activate", methods=["POST"])
def activate_pip(pid):
    _, role = get_caller()
    require_role(role, {"HrbpPartner"})
    p = db.pip_cases.get(pid)
    if not p:
        raise err(ERR_NOT_FOUND, "PIP case not found")
    if p["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "PIP case is not OPEN")
    body = get_body()
    require_fields(body, ["duration_days", "target_score"])
    duration_days = as_int(body["duration_days"], "duration_days")
    if duration_days not in (30, 60, 90):
        raise err(ERR_VALIDATION, "duration_days must be 30, 60, or 90")
    target_score = as_number(body["target_score"], "target_score")
    if not (0 < target_score <= 100):
        raise err(ERR_VALIDATION, "target_score must be in (0,100]")
    p["duration_days"] = duration_days
    p["target_score"] = target_score
    p["status"] = "ACTIVE"
    touch(p)
    return ok_object(pip_view(p))


@bp.route("/pip-cases/<pid>/assess", methods=["POST"])
def assess_pip(pid):
    _, role = get_caller()
    require_role(role, {"HrbpPartner"})
    p = db.pip_cases.get(pid)
    if not p:
        raise err(ERR_NOT_FOUND, "PIP case not found")
    if p["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "PIP case is not ACTIVE")
    body = get_body()
    require_fields(body, ["outcome_score"])
    outcome_score = as_number(body["outcome_score"], "outcome_score")
    if not (0 <= outcome_score <= 100):
        raise err(ERR_VALIDATION, "outcome_score must be in [0,100]")
    p["outcome_score"] = outcome_score
    if outcome_score >= p["target_score"]:
        p["status"] = "CURED"
    else:
        p["status"] = "FAILED"
        emp = db.employees.get(p["employee_id"])
        if emp:
            emp["is_active"] = False
            touch(emp)
    touch(p)
    return ok_object(pip_view(p))
