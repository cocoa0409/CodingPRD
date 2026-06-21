"""Applicant routes (PRD §3.2) — submit, get, list, screen, decide, withdraw."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_int, optional_int, require_enum,
    parse_pagination, paginate, filter_param,
)
from services import domain

bp = Blueprint("applicants", __name__)

APPLICANT_STATUS = {"SUBMITTED", "SCREENED", "APPROVED", "DENIED", "LEASED", "WITHDRAWN"}
DECISIONS = {"APPROVE", "DENY"}


@bp.route("/applicants", methods=["POST"])
def create_applicant():
    require_role({"PropertyManager", "Applicant"})
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    unit_id = require_string(body, "unit_id")
    annual_income = require_int(body, "annual_income_cents", minimum=0)
    credit_score = require_int(body, "credit_score", minimum=300, maximum=850)
    requested_rent = require_int(body, "requested_rent_cents", minimum=1)
    monthly_debt = optional_int(body, "monthly_debt_cents", 0, minimum=0)
    with db.LOCK:
        if unit_id not in db.units:
            raise err(errors.ERR_FK_NOT_FOUND, "unit_id does not resolve")
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "full_name": full_name,
            "email": email,
            "unit_id": unit_id,
            "annual_income_cents": annual_income,
            "credit_score": credit_score,
            "monthly_debt_cents": monthly_debt,
            "requested_rent_cents": requested_rent,
            "status": "SUBMITTED",
            "screening_decision": None,
            "rent_to_income_ratio": None,
            "dti_ratio": None,
        }
        db.applicants[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/applicants/<id>", methods=["GET"])
def get_applicant(id):
    require_role({"PropertyManager", "Applicant"})
    with db.LOCK:
        record = db.applicants.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Applicant not found")
        return object_response(serialize(record), 200)


@bp.route("/applicants", methods=["GET"])
def list_applicants():
    require_role({"PropertyManager"})
    unit_id = filter_param(request.args, "unit_id")
    status = filter_param(request.args, "status")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.applicants.values())
        if unit_id is not None:
            records = [r for r in records if r["unit_id"] == unit_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/applicants/<id>/screen", methods=["POST"])
def screen_applicant(id):
    require_role({"PropertyManager"})
    with db.LOCK:
        applicant = db.applicants.get(id)
        if applicant is None:
            raise err(errors.ERR_NOT_FOUND, "Applicant not found")
        if applicant["status"] != "SUBMITTED":
            raise err(errors.ERR_INVALID_STATE, "Applicant is not SUBMITTED")
        domain.run_screening(applicant)
        applicant["status"] = "SCREENED"
        db.touch(applicant)
        return object_response(serialize(applicant), 200)


@bp.route("/applicants/<id>/decide", methods=["POST"])
def decide_applicant(id):
    require_role({"PropertyManager"})
    body = get_json_body()
    with db.LOCK:
        applicant = db.applicants.get(id)
        if applicant is None:
            raise err(errors.ERR_NOT_FOUND, "Applicant not found")
        decision = require_enum(body, "decision", DECISIONS)
        if applicant["status"] != "SCREENED":
            raise err(errors.ERR_INVALID_STATE, "Applicant is not SCREENED")
        if decision == "APPROVE":
            # Screening gate (priority 8) precedes unit availability (priority 11).
            if applicant["screening_decision"] == "FAIL":
                raise err(errors.ERR_SCREENING_FAILED,
                          "Cannot approve an applicant whose screening failed")
            unit = db.units.get(applicant["unit_id"])
            if unit is None or unit["occupancy_status"] != "VACANT_READY":
                raise err(errors.ERR_UNIT_NOT_AVAILABLE, "Unit is not VACANT_READY")
            applicant["status"] = "APPROVED"
        else:  # DENY
            applicant["status"] = "DENIED"
        db.touch(applicant)
        return object_response(serialize(applicant), 200)


@bp.route("/applicants/<id>/withdraw", methods=["POST"])
def withdraw_applicant(id):
    require_role({"Applicant", "PropertyManager"})
    with db.LOCK:
        applicant = db.applicants.get(id)
        if applicant is None:
            raise err(errors.ERR_NOT_FOUND, "Applicant not found")
        if applicant["status"] not in ("SUBMITTED", "SCREENED", "APPROVED"):
            raise err(errors.ERR_INVALID_STATE,
                      "Applicant cannot be withdrawn from its current state")
        applicant["status"] = "WITHDRAWN"
        db.touch(applicant)
        return object_response(serialize(applicant), 200)
