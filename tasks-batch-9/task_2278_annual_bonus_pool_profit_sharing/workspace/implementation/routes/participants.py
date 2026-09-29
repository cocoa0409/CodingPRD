"""Participant routes.  A participant id doubles as an Employee identity."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (BUSINESS_UNIT_MANAGER, COMPENSATION_COMMITTEE, EMPLOYEE,
                        FINANCE_CONTROLLER, HR_BUSINESS_PARTNER, PLAN_ADMIN,
                        authenticate, get_body, query_param, req_date, req_id,
                        req_int, req_string)
from response import object_response
from routes.common import paginated
from serialize import participant_out
from services import lookup

bp = Blueprint("participants", __name__)

DETAIL_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, BUSINESS_UNIT_MANAGER,
                HR_BUSINESS_PARTNER, FINANCE_CONTROLLER, EMPLOYEE]
LIST_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, BUSINESS_UNIT_MANAGER,
              HR_BUSINESS_PARTNER, FINANCE_CONTROLLER]
SETUP_STATUSES = ("DRAFT", "TARGETS_SET")


@bp.route("/participants", methods=["POST"])
def create_participant():
    authenticate([PLAN_ADMIN])
    body = get_body()

    plan_id = req_id(body, "plan_id")
    business_unit_id = req_id(body, "business_unit_id")
    employee_code = req_string(body, "employee_code")
    full_name = req_string(body, "full_name")
    job_level = req_string(body, "job_level")
    base_salary_cents = req_int(body, "base_salary_cents", minimum=1)
    hire_date = req_date(body, "hire_date")

    plan = lookup.plan(plan_id)
    lookup.business_unit(business_unit_id)

    for existing in db.plan_participants(plan_id):
        if existing["employee_code"] == employee_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "Employee code '%s' already enrolled in this plan"
                           % employee_code)
    if plan["status"] not in SETUP_STATUSES:
        raise ApiError("ERR_PLAN_NOT_IN_SETUP")

    participant = db.base_record()
    participant.update({
        "plan_id": plan_id,
        "business_unit_id": business_unit_id,
        "employee_code": employee_code,
        "full_name": full_name,
        "job_level": job_level,
        "base_salary_cents": base_salary_cents,
        "hire_date": hire_date.isoformat(),
        "employment_status": "ACTIVE",
        "termination_date": None,
        "termination_reason": None,
        "current_job_level": job_level,
        "current_base_salary_cents": base_salary_cents,
        "current_business_unit_id": business_unit_id,
    })
    db.participants[participant["id"]] = participant
    return object_response(participant_out(participant), 201)


@bp.route("/participants/<participant_id>", methods=["GET"])
def get_participant(participant_id):
    authenticate(DETAIL_ROLES)
    return object_response(participant_out(lookup.participant(participant_id)))


@bp.route("/participants", methods=["GET"])
def list_participants():
    authenticate(LIST_ROLES)
    plan_id = query_param("plan_id")
    business_unit_id = query_param("business_unit_id")
    current_business_unit_id = query_param("current_business_unit_id")
    employment_status = query_param("employment_status")
    job_level = query_param("job_level")

    records = db.ordered(db.participants)
    if plan_id is not None:
        records = [r for r in records if r["plan_id"] == plan_id]
    if business_unit_id is not None:
        records = [r for r in records if r["business_unit_id"] == business_unit_id]
    if current_business_unit_id is not None:
        records = [r for r in records
                   if r["current_business_unit_id"] == current_business_unit_id]
    if employment_status is not None:
        records = [r for r in records if r["employment_status"] == employment_status]
    if job_level is not None:
        records = [r for r in records if r["job_level"] == job_level]
    return paginated(records, participant_out)
