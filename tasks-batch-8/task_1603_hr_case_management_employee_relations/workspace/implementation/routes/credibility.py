"""Credibility assessments with dual-variant scoring (PRD §3.4)."""
from flask import Blueprint, request

from db import db
from middleware import authorize, require_investigator
from response import success_object
from services import calculations as calc
from services.core import (
    new_record, require_path, require_ref, list_response, serialize_assessment,
    check_case_not_held,
)
from validate import Payload

bp = Blueprint("credibility", __name__)

READ_ROLES = {"ERManager", "Investigator", "LegalCounsel"}


@bp.post("/er/cases/<cid>/credibility-assessments")
def create_assessment(cid):
    caller = authorize({"Investigator"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    subject_employee_id = p.get_str("subject_employee_id", required=True)
    corroboration_count = p.get_int("corroboration_count", required=True,
                                    minimum=0)
    contradiction_count = p.get_int("contradiction_count", required=True,
                                    minimum=0)
    account_age_days = p.get_int("account_age_days", required=True, minimum=0)

    # priority 5
    if subject_employee_id is not None:
        require_ref("employees", subject_employee_id, "subject_employee_id")

    # priority 7 — litigation-hold freeze (no case-state precondition is
    # declared for recording an assessment)
    check_case_not_held(case)
    # the acting investigator is recorded as the assessor
    inv = require_investigator(caller)

    # priority 24
    p.raise_if_errors()

    score_c, score_r = calc.credibility_scores(corroboration_count,
                                               contradiction_count,
                                               account_age_days)
    # First investigation pass -> CORROBORATION_WEIGHTED; once a case has been
    # REOPENED its assessments are judged RECENCY_WEIGHTED (PRD §3.4).
    variant = "CORROBORATION_WEIGHTED" if case["reopen_count"] == 0 \
        else "RECENCY_WEIGHTED"

    rec = new_record()
    rec.update({
        "case_id": cid,
        "subject_employee_id": subject_employee_id,
        "assessor_investigator_id": inv["id"],
        "corroboration_count": corroboration_count,
        "contradiction_count": contradiction_count,
        "account_age_days": account_age_days,
        "score_corroboration": score_c,
        "score_recency": score_r,
        "active_variant": variant,
    })
    db["credibility_assessments"][rec["id"]] = rec
    return success_object(serialize_assessment(rec), status=201)


@bp.get("/er/cases/<cid>/credibility-assessments")
def list_case_assessments(cid):
    authorize(READ_ROLES)
    require_path("cases", cid)
    items = [a for a in db["credibility_assessments"].values()
             if a["case_id"] == cid]
    return list_response(items, serialize_assessment)


@bp.get("/er/credibility-assessments/<aid>")
def get_assessment(aid):
    authorize(READ_ROLES)
    rec = require_path("credibility_assessments", aid)
    return success_object(serialize_assessment(rec))


@bp.get("/er/credibility-assessments")
def list_assessments():
    authorize(READ_ROLES)
    items = list(db["credibility_assessments"].values())
    for field in ("subject_employee_id", "assessor_investigator_id"):
        v = request.args.get(field)
        if v is not None:
            items = [a for a in items if a.get(field) == v]
    return list_response(items, serialize_assessment)
