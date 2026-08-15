"""Patient intake (PRD 3.2)."""
from flask import Blueprint

from db import db, next_seq
from middleware import authorized
from response import success_object
from routes.helpers import ALL_ROLES, get_patient
from serializers import serialize
from util import new_id, CLOCK
from validate import get_body, req_str, req_int, req_dt, opt_bool, opt_int

bp = Blueprint("patients", __name__)


@bp.post("/infusion/patients")
def create_patient():
    authorized(["AuthCoordinator"])
    body = get_body()
    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "member_id": req_str(body, "member_id"),
        "full_name": req_str(body, "full_name"),
        "diagnosis_code": req_str(body, "diagnosis_code"),
        "payer_code": req_str(body, "payer_code"),
        "plan_year_end": req_dt(body, "plan_year_end"),
        "deductible_remaining_cents": req_int(body, "deductible_remaining_cents"),
        "oop_remaining_cents": req_int(body, "oop_remaining_cents"),
        "rural_resident": opt_bool(body, "rural_resident", False),
        "travel_minutes_to_hospital": opt_int(body, "travel_minutes_to_hospital", 0),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["patients"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/infusion/patients/<pid>")
def read_patient(pid):
    authorized(ALL_ROLES)
    return success_object(serialize(get_patient(pid)))
