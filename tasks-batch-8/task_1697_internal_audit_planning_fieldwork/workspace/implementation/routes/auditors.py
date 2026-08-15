"""Auditor endpoints (PRD 3.4): roster maintenance."""
from flask import Blueprint

from errors import raise_error, ERR_AUDITOR_INACTIVE
from middleware import authorized
from response import success_object
from routes.helpers import get_one
from services.core import new_record, public, touch
from validate import check_unknown_fields, get_body, opt_str_list, req_enum, req_str, require_path

bp = Blueprint("auditors", __name__)

CREATE_FIELDS = {"full_name", "grade", "skills"}
GRADES = ("STAFF", "SENIOR", "MANAGER", "DIRECTOR")


@bp.post("/audit/auditors")
def create_auditor():
    authorized(["AuditAdmin"])
    body = get_body()
    check_unknown_fields(body, CREATE_FIELDS)
    full_name = req_str(body, "full_name")
    grade = req_enum(body, "grade", GRADES)
    skills = opt_str_list(body, "skills", [])
    rec = new_record("auditors", {
        "full_name": full_name,
        "grade": grade,
        "skills": skills,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/audit/auditors/<rid>")
def get_auditor(rid):
    return get_one("auditors", rid)


@bp.post("/audit/auditors/<rid>/deactivate")
def deactivate_auditor(rid):
    authorized(["AuditAdmin"])
    auditor = require_path("auditors", rid)
    # Stage 7: must be ACTIVE (double deactivation -> ERR_AUDITOR_INACTIVE)
    if auditor["status"] != "ACTIVE":
        raise_error(ERR_AUDITOR_INACTIVE, "auditor is already INACTIVE")
    auditor["status"] = "INACTIVE"
    touch(auditor)
    return success_object(public(auditor))
