"""ArticulationAgreement endpoints (PRD 3.9).

Unlike terms, articulation windows are CLOSED intervals — agreements on the
same (course_id, target_institution) conflict even when they merely touch.
"""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_ARTICULATION_WINDOW_OVERLAP
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.core import new_record, public
from validate import (
    get_body,
    opt_enum,
    req_dt,
    req_number,
    req_str,
    require_body_ref,
)

bp = Blueprint("articulation_agreements", __name__)

MIN_GRADES = {"A", "B", "C"}


@bp.post("/articulation-agreements")
def create_articulation_agreement():
    authorized(["DualCreditAdmin"])
    body = get_body()
    course_id = req_str(body, "course_id")
    target_institution = req_str(body, "target_institution")
    transfer_credit_hours = req_number(body, "transfer_credit_hours", gt=0)
    min_grade_for_transfer = opt_enum(
        body, "min_grade_for_transfer", MIN_GRADES, default="C"
    )
    from_raw, effective_from = req_dt(body, "effective_from")
    to_raw, effective_to = req_dt(body, "effective_to")

    # Priority 5: referenced course exists.
    require_body_ref("courses", course_id, "course_id")

    # Priority 8: CLOSED-interval overlap on (course_id, target_institution);
    # touching endpoints DO conflict.
    for a in db["articulation_agreements"].values():
        if (
            a["course_id"] == course_id
            and a["target_institution"] == target_institution
            and effective_from <= a["_effective_to"]
            and a["_effective_from"] <= effective_to
        ):
            raise_error(
                ERR_ARTICULATION_WINDOW_OVERLAP,
                "window overlaps an existing agreement for this course and target",
            )

    rec = new_record(
        "articulation_agreements",
        {
            "course_id": course_id,
            "target_institution": target_institution,
            "transfer_credit_hours": transfer_credit_hours,
            "min_grade_for_transfer": min_grade_for_transfer,
            "effective_from": from_raw,
            "effective_to": to_raw,
        },
    )
    rec["_effective_from"] = effective_from
    rec["_effective_to"] = effective_to
    return success_object(public(rec), status=201)


@bp.get("/articulation-agreements")
def list_articulation_agreements():
    return list_response(
        "articulation_agreements",
        {
            "course_id": arg("course_id"),
            "target_institution": arg("target_institution"),
        },
    )


@bp.get("/articulation-agreements/<rid>")
def get_articulation_agreement(rid):
    return get_one("articulation_agreements", rid)
