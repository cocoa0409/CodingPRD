"""CompensationPackage endpoints (PRD §3.2): cyclic DRAFT/SUBMITTED/APPROVED."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DUPLICATE_PACKAGE,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, touch
from validate import get_body, opt_int, req_field, req_int, req_str, require_fk, require_path_resource

bp = Blueprint("compensation_packages", __name__)

OPEN_PACKAGE_STATES = {"DRAFT", "SUBMITTED", "APPROVED"}


@bp.post("/mobility/compensation-packages")
def create_package():
    caller = authorized(["PayrollSpecialist", "MobilityAdmin"])
    body = get_body()
    asg = require_fk("assignments", req_field(body, "assignment_id"), "assignment_id")
    letter_title = req_str(body, "letter_title")
    home_base_annual_cents = req_int(body, "home_base_annual_cents", minimum=0)
    goods_services_differential_pct = opt_int(body, "goods_services_differential_pct", 0, minimum=0)
    relocation_lump_sum_cents = opt_int(body, "relocation_lump_sum_cents", 0, minimum=0)
    # Uniqueness: at most one open package per assignment.
    for p in db["compensation_packages"].values():
        if p["assignment_id"] == asg["id"] and p["status"] in OPEN_PACKAGE_STATES:
            raise_error(ERR_DUPLICATE_PACKAGE, "an open compensation package already exists")
    rec = new_record("compensation_packages", {
        "assignment_id": asg["id"],
        "letter_title": letter_title,
        "home_base_annual_cents": home_base_annual_cents,
        "goods_services_differential_pct": goods_services_differential_pct,
        "relocation_lump_sum_cents": relocation_lump_sum_cents,
        "status": "DRAFT",
        "revision_number": 0,
        "created_by_user_id": caller.user_id,
        "approved_by_user_id": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/mobility/compensation-packages/<rid>")
def get_package(rid):
    return get_one("compensation_packages", rid)


@bp.get("/mobility/compensation-packages")
def list_packages():
    return list_response("compensation_packages", {
        "assignment_id": request.args.get("assignment_id"),
    })


@bp.post("/mobility/compensation-packages/<rid>/submit")
def submit_package(rid):
    authorized(["PayrollSpecialist"])
    pkg = require_path_resource("compensation_packages", rid)
    if pkg["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT package can be submitted")
    pkg["status"] = "SUBMITTED"
    touch(pkg)
    return success_object(public(pkg))


@bp.post("/mobility/compensation-packages/<rid>/approve")
def approve_package(rid):
    caller = authorized(["MobilityApprover"])
    pkg = require_path_resource("compensation_packages", rid)
    if pkg["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "only a SUBMITTED package can be approved")
    if caller.user_id == pkg["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "the package approver must differ from its creator")
    pkg["status"] = "APPROVED"
    pkg["approved_by_user_id"] = caller.user_id
    touch(pkg)
    return success_object(public(pkg))


@bp.post("/mobility/compensation-packages/<rid>/revise")
def revise_package(rid):
    authorized(["PayrollSpecialist"])
    pkg = require_path_resource("compensation_packages", rid)
    if pkg["status"] not in ("SUBMITTED", "APPROVED"):
        raise_error(ERR_INVALID_STATE, "only a SUBMITTED or APPROVED package can be revised")
    if pkg["status"] == "APPROVED":
        asg = db["assignments"].get(pkg["assignment_id"])
        if asg is None or asg["status"] != "DRAFT":
            raise_error(
                ERR_INVALID_STATE,
                "an APPROVED package can be revised only while the assignment is still DRAFT",
            )
    pkg["status"] = "DRAFT"
    pkg["revision_number"] += 1
    pkg["approved_by_user_id"] = None
    touch(pkg)
    return success_object(public(pkg))
