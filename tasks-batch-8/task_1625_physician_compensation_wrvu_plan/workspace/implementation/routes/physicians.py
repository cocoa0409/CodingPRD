"""Physician roster endpoints (PRD 3.1)."""
import re

from flask import Blueprint

from db import db
from errors import raise_error, ERR_VALIDATION, ERR_NOT_FOUND, ERR_NOT_OWN_RESOURCE
from middleware import authorized
from response import success_object
from services.core import new_record, public
from validate import get_body, req_str, req_enum, req_number, req_date
from util import dec

bp = Blueprint("physicians", __name__)

READ_ROLES = ["SystemAdmin", "CompAnalyst", "CompCommittee", "ComplianceOfficer", "Physician"]


@bp.post("/physicians")
def create_physician():
    authorized(["SystemAdmin"])
    body = get_body()
    npi = req_str(body, "npi")
    full_name = req_str(body, "full_name")
    specialty = req_str(body, "specialty")
    provider_type = req_enum(body, "provider_type", {"PHYSICIAN", "APP"})
    fte = req_number(body, "fte")
    hire_date = req_date(body, "hire_date")
    if not re.fullmatch(r"\d{10}", npi):
        raise_error(ERR_VALIDATION, "npi must be exactly 10 digits")
    if not (dec(fte) > 0 and dec(fte) <= 1):
        raise_error(ERR_VALIDATION, "fte must be in (0, 1.0]")
    for p in db["physicians"].values():
        if p["npi"] == npi:
            raise_error(ERR_VALIDATION, "npi must be unique across all physicians")
    rec = new_record("physicians", {
        "npi": npi,
        "full_name": full_name,
        "specialty": specialty,
        "provider_type": provider_type,
        "fte": fte,
        "hire_date": hire_date,
    })
    return success_object(public(rec), status=201)


@bp.get("/physicians/<rid>")
def get_physician(rid):
    caller = authorized(READ_ROLES)
    # Ownership (priority 3) precedes existence for the Physician role: the
    # check is determinable from the path id alone.
    if caller.role == "Physician" and caller.user_id != rid:
        raise_error(ERR_NOT_OWN_RESOURCE, "a Physician may read only its own record")
    rec = db["physicians"].get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"physician not found: {rid}")
    return success_object(public(rec))
