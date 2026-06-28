"""Applicant & eligibility routes (PRD §3.3)."""
from flask import Blueprint

import errors
from db import db, stamp_create, touch
from middleware import get_identity, require_roles
from response import object_response
from services import calc, serialize
from services import common

bp = Blueprint("applicants", __name__)

HISTORY_FLAGS = {"CLEAN", "MINOR", "SEVERE"}


@bp.route("/applicants", methods=["POST"])
def create_applicant():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "Member"})  # shared (PRD §3.3)
    body = common.get_body()
    full_name = common.require_str(body, "full_name")
    email = common.require_str(body, "email")
    credit_score = common.require_int(body, "credit_score", min_value=300, max_value=850)
    income = common.require_int(body, "monthly_income_cents", min_value=0)
    history = common.require_enum(body, "history_flag", HISTORY_FLAGS)

    # email unique across applicants (priority 13, ERR_DUPLICATE_VALUE).
    for a in db.applicants.values():
        if a["email"] == email:
            raise errors.duplicate_value("Applicant email already exists.")

    rec = {
        "full_name": full_name,
        "email": email,
        "credit_score": credit_score,
        "monthly_income_cents": income,
        "history_flag": history,
        # computed fields null until a decision is made (PRD §3.3).
        "eligibility_status": None,
        "eligibility_score": None,
        "required_deposit_cents": None,
    }
    stamp_create(rec)
    db.applicants[rec["id"]] = rec
    return object_response(serialize.serialize_applicant(rec), 201)


@bp.route("/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    rec = common.resolve(db.applicants, aid)
    return object_response(serialize.serialize_applicant(rec))


@bp.route("/applicants/<aid>/decide-eligibility", methods=["POST"])
def decide_eligibility(aid):
    _, role = get_identity()
    require_roles(role, {"BillingAdmin", "PlatformAdmin"})  # shared (PRD §3.3)
    applicant = common.resolve(db.applicants, aid)
    body = common.get_body()
    plan_id = common.require_str(body, "plan_id")
    plan = common.resolve(db.subscription_plans, plan_id)

    status, score, deposit = calc.eligibility_decision(applicant, plan)
    applicant["eligibility_status"] = status
    applicant["eligibility_score"] = score
    applicant["required_deposit_cents"] = deposit
    touch(applicant)
    return object_response(serialize.serialize_applicant(applicant))
