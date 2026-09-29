"""Partner institutions and the receiving-eligibility cascade."""

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc, engine

bp = Blueprint("institutions", __name__)

ACCREDITATION_STATUSES = ("ACCREDITED", "PROVISIONAL", "NON_ACCREDITED", "SUSPENDED")
INSTITUTION_COMPUTED = ("is_receiving_eligible",)


@bp.route("/aquarium/institutions", methods=["POST"])
def create_institution():
    M.authenticate({M.DIRECTOR})
    body = M.json_body()
    V.reject_computed(body, INSTITUTION_COMPUTED)
    name = V.as_str(body, "name", required=True)
    code = V.as_str(body, "institution_code", required=True)
    status = V.as_enum(body, "accreditation_status", ACCREDITATION_STATUSES, required=True)
    score = V.as_dec(body, "welfare_audit_score", required=True, minimum=0, maximum=100)
    last_audit_at = V.as_dt(body, "last_audit_at")

    for row in db.db.institutions.values():
        if row["institution_code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE")

    row = db.new_row()
    row.update({
        "name": name,
        "institution_code": code,
        "accreditation_status": status,
        "welfare_audit_score": score,
        "last_audit_at": last_audit_at,
        "is_receiving_eligible": False,
    })
    row["is_receiving_eligible"] = calc.is_receiving_eligible(row)
    db.insert("institutions", row)
    return response.object_response(S.institution(row), 201)


@bp.route("/aquarium/institutions", methods=["GET"])
def list_institutions():
    M.authenticate(M.ANY_ROLE)
    status = M.enum_param("accreditation_status", ACCREDITATION_STATUSES)
    eligible = M.bool_param("is_receiving_eligible")
    limit, offset = M.pagination()

    def keep(row):
        if status is not None and row["accreditation_status"] != status:
            return False
        if eligible is not None and row["is_receiving_eligible"] != eligible:
            return False
        return True

    rows = db.ordered("institutions", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.institution(r) for r in page], limit, offset, total)


@bp.route("/aquarium/institutions/<row_id>", methods=["GET"])
def get_institution(row_id):
    M.authenticate(M.ANY_ROLE)
    row = M.fetch("institutions", row_id)
    return response.object_response(S.institution(row))


@bp.route("/aquarium/institutions/<row_id>", methods=["PATCH"])
def patch_institution(row_id):
    M.authenticate({M.DIRECTOR})
    institution = M.fetch("institutions", row_id)
    body = M.json_body()
    V.reject_computed(body, INSTITUTION_COMPUTED)
    status = V.as_enum(body, "accreditation_status", ACCREDITATION_STATUSES)
    score = V.as_dec(body, "welfare_audit_score", minimum=0, maximum=100)
    last_audit_at = V.as_dt(body, "last_audit_at")

    was_eligible = institution["is_receiving_eligible"]
    if status is not None:
        institution["accreditation_status"] = status
    if score is not None:
        institution["welfare_audit_score"] = score
    if last_audit_at is not None:
        institution["last_audit_at"] = last_audit_at
    institution["is_receiving_eligible"] = calc.is_receiving_eligible(institution)
    db.touch(institution)

    if was_eligible and not institution["is_receiving_eligible"]:
        engine.cascade_institution_ineligible(institution)
    return response.object_response(S.institution(institution))
