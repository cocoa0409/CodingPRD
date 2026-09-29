"""Suppliers and the qualification ladder (PRD 3.7)."""

from flask import Blueprint

import auth
import calc
import cascade
import db
import errors
import response
import serialize
import validate
from errors import fail
from routes.helpers import PREFIX, listing, path_row

bp = Blueprint("suppliers", __name__)

READ_ROLES = (
    auth.ROLE_QA,
    auth.ROLE_SPECIALIST,
    auth.ROLE_SUPPLIER_REP,
    auth.ROLE_AUDITOR,
)
LIST_ROLES = (auth.ROLE_QA, auth.ROLE_SPECIALIST, auth.ROLE_AUDITOR)

# decision -> (required current status, resulting status)
DECISION_EDGES = {
    "QUALIFY": ("UNQUALIFIED", "QUALIFIED"),
    "PROBATION": ("QUALIFIED", "PROBATION"),
    "REINSTATE": ("PROBATION", "QUALIFIED"),
    "DISQUALIFY": ("PROBATION", "DISQUALIFIED"),
}


@bp.route(PREFIX + "/suppliers", methods=["POST"])
@auth.endpoint([auth.ROLE_QA])
def create_supplier():
    body = validate.body()
    supplier_name = validate.req_str(body, "supplier_name")
    country_code = validate.req_str(body, "country_code")
    audit_score = validate.opt_int(body, "audit_score", ge=0, le=100)

    row = db.base_fields()
    row.update(
        {
            "supplier_name": supplier_name,
            "country_code": country_code,
            "qualification_status": "UNQUALIFIED",
            "audit_score": audit_score,
            "coa_rejection_count": 0,
            "total_released_kg": calc.d2(0),
            "remediation_reference": None,
            "last_decision_at": None,
        }
    )
    db.insert("suppliers", row)
    return response.object_response(serialize.supplier(row), 201)


@bp.route(PREFIX + "/suppliers/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_supplier(row_id):
    row = path_row("suppliers", row_id, errors.ERR_SUPPLIER_NOT_FOUND)
    return response.object_response(serialize.supplier(row))


@bp.route(PREFIX + "/suppliers", methods=["GET"])
@auth.endpoint(LIST_ROLES)
def list_suppliers():
    return listing(
        "suppliers", serialize.supplier, filters=("qualification_status", "country_code")
    )


@bp.route(PREFIX + "/suppliers/<row_id>/qualification-decision", methods=["POST"])
@auth.endpoint([auth.ROLE_QA])
def qualification_decision(row_id):
    row = path_row("suppliers", row_id, errors.ERR_SUPPLIER_NOT_FOUND)
    body = validate.body()
    decision = validate.req_enum(body, "decision", calc.SUPPLIER_DECISIONS)
    audit_score = validate.opt_int(body, "audit_score", ge=0, le=100)
    remediation_reference = validate.opt_str(body, "remediation_reference")

    required_from, resulting = DECISION_EDGES[decision]
    if row["qualification_status"] != required_from:
        fail(
            errors.ERR_SUPPLIER_STATE_INVALID,
            "%s is only legal from %s, not from %s."
            % (decision, required_from, row["qualification_status"]),
        )

    if decision == "QUALIFY":
        # The body score wins; otherwise the score captured at registration is used.
        effective_score = audit_score if audit_score is not None else row["audit_score"]
        if effective_score is None or effective_score < calc.AUDIT_SCORE_FLOOR:
            fail(
                errors.ERR_AUDIT_SCORE_INSUFFICIENT,
                "A qualification audit score of at least %s is required."
                % calc.AUDIT_SCORE_FLOOR,
            )
    if decision == "REINSTATE" and not remediation_reference:
        fail(
            errors.ERR_REMEDIATION_REFERENCE_REQUIRED,
            "REINSTATE requires a non-empty remediation_reference.",
        )

    row["qualification_status"] = resulting
    row["last_decision_at"] = db.now()
    if decision == "QUALIFY" and audit_score is not None:
        row["audit_score"] = audit_score
    if decision == "REINSTATE":
        row["coa_rejection_count"] = 0
        row["remediation_reference"] = remediation_reference
    db.touch(row)

    cascade.supplier_qualification_cascade(row)
    return response.object_response(serialize.supplier(row))
