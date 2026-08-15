"""Oath ceremonies: create, assign, conclude, cancel."""
from flask import Blueprint

from auth import authenticate, require_roles, ROLES
from db import db, Rec, stamp_new, bump, now_dt
from errors import err_not_found, err_invalid_state, err_stale_version, conflict
from services import ser_ceremony, ser_case
from util import json_body, success_obj, v_str, v_int, v_datetime

bp = Blueprint("ceremonies", __name__)


def _get_ceremony(ceremony_id):
    c = db.ceremonies.get(ceremony_id)
    if c is None:
        raise err_not_found("Oath ceremony not found")
    return c


@bp.post("/naturalization/oath-ceremonies")
def create_ceremony():
    body = json_body()
    raw_date, dt_date = v_datetime(body, "ceremony_date")
    venue = v_str(body, "venue")
    capacity = v_int(body, "capacity", minv=1)
    authenticate()
    require_roles("ProgramAdmin")
    c = Rec(ceremony_date_raw=raw_date, ceremony_date_dt=dt_date, venue=venue,
            capacity=capacity, assigned_count=0, status="SCHEDULED")
    stamp_new(c)
    db.ceremonies[c.id] = c
    return success_obj(ser_ceremony(c), 201)


@bp.get("/naturalization/oath-ceremonies/<ceremony_id>")
def get_ceremony(ceremony_id):
    authenticate()
    require_roles(*ROLES)
    return success_obj(ser_ceremony(_get_ceremony(ceremony_id)))


@bp.post("/naturalization/oath-ceremonies/<ceremony_id>/assign")
def assign_case(ceremony_id):
    body = json_body()
    case_id = v_str(body, "case_id")
    expected_version = v_int(body, "expected_ceremony_version")
    authenticate()
    require_roles("IntakeCoordinator", "ProgramAdmin")
    ceremony = _get_ceremony(ceremony_id)
    case = db.cases.get(case_id)
    if case is None:
        raise err_not_found("Case not found")
    if ceremony.status != "SCHEDULED":
        raise err_invalid_state("Ceremony is not SCHEDULED")
    if case.stage != "APPROVED_PENDING_OATH":
        raise conflict("ERR_CASE_NOT_OATH_READY",
                       "Case is not APPROVED_PENDING_OATH")
    if case.rfe_status != "NONE":
        raise conflict("ERR_RFE_OPEN",
                       "Oath assignment is blocked while an RFE is open")
    if ceremony.assigned_count >= ceremony.capacity:
        raise conflict("ERR_CEREMONY_FULL", "Ceremony is at capacity")
    if expected_version != ceremony.version:
        raise err_stale_version()
    case.stage = "OATH_SCHEDULED"
    case.oath_ceremony_id = ceremony.id
    bump(case)
    ceremony.assigned_count += 1
    bump(ceremony)
    return success_obj(ser_case(case))


@bp.post("/naturalization/oath-ceremonies/<ceremony_id>/conclude")
def conclude_ceremony(ceremony_id):
    json_body()
    authenticate()
    require_roles("ProgramAdmin")
    ceremony = _get_ceremony(ceremony_id)
    if ceremony.status != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED ceremony may be concluded")
    if now_dt() < ceremony.ceremony_date_dt:
        raise conflict("ERR_CEREMONY_NOT_YET_HELD",
                       "Ceremony date has not yet been reached")
    for case in db.cases.values():
        if case.oath_ceremony_id == ceremony.id and case.stage == "OATH_SCHEDULED":
            case.stage = "NATURALIZED"
            bump(case)
            applicant = db.applicants.get(case.applicant_id)
            if applicant is not None:
                applicant.stage = "NATURALIZED"
                applicant.voter_registration_referred = True
                bump(applicant)
    ceremony.status = "CONCLUDED"
    bump(ceremony)
    return success_obj(ser_ceremony(ceremony))


@bp.post("/naturalization/oath-ceremonies/<ceremony_id>/cancel")
def cancel_ceremony(ceremony_id):
    json_body()
    authenticate()
    require_roles("ProgramAdmin")
    ceremony = _get_ceremony(ceremony_id)
    if ceremony.status != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED ceremony may be cancelled")
    reverted = 0
    for case in db.cases.values():
        if case.oath_ceremony_id == ceremony.id and case.stage == "OATH_SCHEDULED":
            case.stage = "APPROVED_PENDING_OATH"
            case.oath_ceremony_id = None
            bump(case)
            reverted += 1
    ceremony.assigned_count -= reverted
    ceremony.status = "CANCELLED"
    bump(ceremony)
    return success_obj(ser_ceremony(ceremony))
