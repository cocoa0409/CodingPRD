"""Candidate endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_DUPLICATE_EMPLOYEE_ID, ERR_CANDIDATE_NOT_FOUND
from middleware import authorized, ALL_READ_ROLES
from response import success_object
from routes.helpers import public, get_one
from services.core import new_record
from validate import get_body, req_str, req_datetime_str, require_path, raw_str

bp = Blueprint("candidates", __name__)


@bp.post("/candidates")
def create_candidate():
    authorized(["ProvostOfficer"])
    body = get_body()
    # Priority 9 structural, listed order: duplicate employee_id, then shape.
    employee_id_raw = raw_str(body, "employee_id")
    if employee_id_raw is not None:
        for c in db["candidates"].values():
            if c["employee_id"] == employee_id_raw:
                raise_error(ERR_DUPLICATE_EMPLOYEE_ID, "employee_id already registered")
    full_name = req_str(body, "full_name")
    employee_id = req_str(body, "employee_id")
    department = req_str(body, "department")
    college = req_str(body, "college")
    tenure_clock_start = req_datetime_str(body, "tenure_clock_start")
    rec = new_record("candidates", {
        "full_name": full_name,
        "employee_id": employee_id,
        "department": department,
        "college": college,
        "tenure_clock_start": tenure_clock_start,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/candidates/<rid>")
def get_candidate(rid):
    return get_one("candidates", rid, ERR_CANDIDATE_NOT_FOUND)
