"""ExternalAid endpoints (PRD 3.8)."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, public
from services.packaging import run_overaward_detection
from validate import (
    get_body, req_str, req_int, opt_bool, require_path_resource, deferred_body_ref,
)

bp = Blueprint("external_aid", __name__)

DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]


@bp.post("/external-aid")
def create_external_aid():
    authorized(["AidOfficer"])
    body = get_body()
    # Rung 4: body foreign keys (absent keys defer to the rung-9 shape check).
    student = deferred_body_ref("students", body, "student_id")
    aid_year = deferred_body_ref("aid_years", body, "aid_year_id")
    # Rung 9: shape.
    req_str(body, "student_id")
    req_str(body, "aid_year_id")
    source_name = req_str(body, "source_name")
    amount = req_int(body, "amount_cents")
    if amount <= 0:
        raise_error(ERR_INVALID_REQUEST, "amount_cents must be strictly positive")
    counts = opt_bool(body, "counts_against_coa", True)
    rec = new_record("external_aid", {
        "student_id": student["id"],
        "aid_year_id": aid_year["id"],
        "source_name": source_name,
        "amount_cents": amount,
        "counts_against_coa": counts,
    })
    # Reporting external aid immediately triggers over-award detection.
    run_overaward_detection(student["id"], aid_year["id"])
    return success_object(public(rec), status=201)


@bp.get("/external-aid")
def list_external_aid():
    authorized(DIRECTOR_OFFICER)
    return list_response("external_aid", {
        "student_id": request.args.get("student_id"),
        "aid_year_id": request.args.get("aid_year_id"),
    })


@bp.get("/external-aid/<rid>")
def get_external_aid(rid):
    authorized(DIRECTOR_OFFICER)
    rec = require_path_resource("external_aid", rid)
    return success_object(public(rec))
