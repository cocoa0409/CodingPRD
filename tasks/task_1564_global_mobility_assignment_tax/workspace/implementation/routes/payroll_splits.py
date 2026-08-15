"""PayrollSplit endpoints (PRD §3.2): DRAFT/ACTIVE/SUSPENDED/TERMINATED."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DUPLICATE_SPLIT,
    ERR_INVALID_STATE,
    ERR_SPLIT_SUM_INVALID,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, touch
from validate import get_body, opt_bool, req_field, req_int, require_fk, require_path_resource

bp = Blueprint("payroll_splits", __name__)

OPEN_SPLIT_STATES = {"DRAFT", "ACTIVE", "SUSPENDED"}


@bp.post("/mobility/payroll-splits")
def create_split():
    authorized(["PayrollSpecialist"])
    body = get_body()
    asg = require_fk("assignments", req_field(body, "assignment_id"), "assignment_id")
    home_payroll_pct = req_int(body, "home_payroll_pct", minimum=0, maximum=100)
    host_payroll_pct = req_int(body, "host_payroll_pct", minimum=0, maximum=100)
    shadow_payroll_host = opt_bool(body, "shadow_payroll_host", True)
    # Uniqueness (priority 10) precedes the sum check, per the catalog order.
    for sp in db["payroll_splits"].values():
        if sp["assignment_id"] == asg["id"] and sp["status"] in OPEN_SPLIT_STATES:
            raise_error(ERR_DUPLICATE_SPLIT, "an open payroll split already exists")
    if home_payroll_pct + host_payroll_pct != 100:
        raise_error(ERR_SPLIT_SUM_INVALID, "home_payroll_pct + host_payroll_pct must equal 100")
    rec = new_record("payroll_splits", {
        "assignment_id": asg["id"],
        "home_payroll_pct": home_payroll_pct,
        "host_payroll_pct": host_payroll_pct,
        "shadow_payroll_host": shadow_payroll_host,
        "coc_exempt": False,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/mobility/payroll-splits/<rid>")
def get_split(rid):
    return get_one("payroll_splits", rid)


@bp.get("/mobility/payroll-splits")
def list_splits():
    return list_response("payroll_splits", {
        "assignment_id": request.args.get("assignment_id"),
    })


@bp.post("/mobility/payroll-splits/<rid>/activate")
def activate_split(rid):
    authorized(["PayrollSpecialist"])
    sp = require_path_resource("payroll_splits", rid)
    if sp["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT split can be activated")
    if sp["home_payroll_pct"] + sp["host_payroll_pct"] != 100:
        raise_error(ERR_SPLIT_SUM_INVALID, "home_payroll_pct + host_payroll_pct must equal 100")
    sp["status"] = "ACTIVE"
    touch(sp)
    return success_object(public(sp))


@bp.post("/mobility/payroll-splits/<rid>/suspend")
def suspend_split(rid):
    authorized(["PayrollSpecialist"])
    sp = require_path_resource("payroll_splits", rid)
    if sp["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE split can be suspended")
    sp["status"] = "SUSPENDED"
    touch(sp)
    return success_object(public(sp))


@bp.post("/mobility/payroll-splits/<rid>/resume")
def resume_split(rid):
    authorized(["PayrollSpecialist"])
    sp = require_path_resource("payroll_splits", rid)
    if sp["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "only a SUSPENDED split can be resumed")
    asg = db["assignments"].get(sp["assignment_id"])
    if asg is None or asg["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "the linked assignment must be ACTIVE to resume the split")
    sp["status"] = "ACTIVE"
    touch(sp)
    return success_object(public(sp))


@bp.post("/mobility/payroll-splits/<rid>/terminate")
def terminate_split(rid):
    authorized(["PayrollSpecialist"])
    sp = require_path_resource("payroll_splits", rid)
    if sp["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_INVALID_STATE, "only an ACTIVE or SUSPENDED split can be terminated")
    sp["status"] = "TERMINATED"
    touch(sp)
    return success_object(public(sp))
