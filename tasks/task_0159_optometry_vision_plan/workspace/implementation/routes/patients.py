"""Patient registration, retrieval, statement."""
from flask import Blueprint, request

import clock
import errors
import helpers
import response
import serialize
from db import db, new_id, stamp_create
from middleware import require_roles

bp = Blueprint("patients", __name__)

ALL_ROLES = ("FrontDesk", "Optometrist", "Optician", "Biller")
PLAN_CARRIERS = {"VSP", "EYEMED", "NONE"}

_STATEMENT_STATUSES = {"ADJUDICATED", "SETTLED_PARTIAL"}


@bp.post("/patients")
@require_roles("FrontDesk")
def create_patient():
    body = helpers.get_json_body()
    full_name = helpers.require_str(body, "full_name")
    dob = helpers.require_str(body, "date_of_birth")
    dob_date = clock.parse_date(dob)
    if dob_date is None:
        raise errors.invalid_request("date_of_birth must be a valid ISO date")
    if dob_date >= clock.current_date():
        raise errors.invalid_request("date_of_birth must be in the past")
    plan_carrier = helpers.require_enum(body, "plan_carrier", PLAN_CARRIERS)
    medical = helpers.require_bool(body, "medical_insurance_on_file",
                                   required=False, default=False)
    recall = helpers.require_int(body, "recall_interval_months", required=False,
                                 minimum=1, maximum=36, default=12)

    record = {
        "id": new_id(),
        "full_name": full_name,
        "date_of_birth": dob,
        "plan_carrier": plan_carrier,
        "medical_insurance_on_file": medical,
        "recall_interval_months": recall,
        "last_routine_exam_date": None,
        "outstanding_patient_balance_cents": 0,
    }
    stamp_create(record)
    db.patients[record["id"]] = record
    return response.object_response(serialize.patient(record), 201)


@bp.get("/patients/<patient_id>")
@require_roles(*ALL_ROLES)
def get_patient(patient_id):
    record = db.patients.get(patient_id)
    if record is None:
        raise errors.not_found("Patient not found")
    return response.object_response(serialize.patient(record), 200)


@bp.get("/patients")
@require_roles("FrontDesk", "Biller")
def list_patients():
    limit, offset = helpers.parse_pagination()
    plan_carrier = request.args.get("plan_carrier")
    records = list(db.patients.values())
    if plan_carrier is not None:
        records = [r for r in records if r["plan_carrier"] == plan_carrier]
    page, total = helpers.paginate(records, limit, offset)
    return response.array_response(
        [serialize.patient(r) for r in page], limit, offset, total, 200)


@bp.get("/patients/<patient_id>/statement")
@require_roles("FrontDesk", "Biller")
def patient_statement(patient_id):
    patient = db.patients.get(patient_id)
    if patient is None:
        raise errors.not_found("Patient not found")

    # Claims in scope ordered by creation ascending (PRD §3.10).
    claims = [c for c in db.claims.values()
              if c.get("patient_id") == patient_id
              and c["claim_status"] in _STATEMENT_STATUSES]
    claims.sort(key=lambda c: c.get("_seq", 0))

    total = 0
    for c in claims:
        outstanding = c["patient_responsibility_cents"] - c["settled_cents"]
        # round each line to whole dollars (multiple of 100 cents), half up, THEN sum
        dollars = helpers.round_half_up(outstanding / 100)
        total += dollars * 100

    return response.object_response({
        "patient_id": patient_id,
        "statement_total_cents": total,
        "line_count": len(claims),
    }, 200)
