"""Security risk assessments (PRD 3.10)."""

from flask import Blueprint

import clock
import db
import response
from errors import fail
from middleware import STAFF, require
from routes.common import check_state, filter_rows, load
from services import posture
from services.calc import residual_risk_score
from validators import F, no_body, parse, supplied

bp = Blueprint("security", __name__, url_prefix="/health-data/security-risk-assessments")

TABLE = "security_risk_assessments"

_SCORES = {
    "admin_control_score": F("int", minimum=0, maximum=100),
    "technical_control_score": F("int", minimum=0, maximum=100),
    "physical_control_score": F("int", minimum=0, maximum=100),
    "vendor_oversight_score": F("int", minimum=0, maximum=100),
    "documented_gap_count": F("int", minimum=0),
}

_PATCH = {
    "admin_control_score": F("int", required=False, minimum=0, maximum=100),
    "technical_control_score": F("int", required=False, minimum=0, maximum=100),
    "physical_control_score": F("int", required=False, minimum=0, maximum=100),
    "vendor_oversight_score": F("int", required=False, minimum=0, maximum=100),
    "documented_gap_count": F("int", required=False, minimum=0),
    "remediation_plan_present": F("bool", required=False),
}


def _rescore(row):
    score, tier = residual_risk_score(row)
    row["residual_risk_score"] = score
    row["risk_tier"] = tier


@bp.post("")
def create_assessment():
    require("SecurityEngineer")
    fields = {"app_product_id": F("string"), "assessment_label": F("string")}
    fields.update(_SCORES)
    fields["remediation_plan_present"] = F("bool", required=False)
    body = parse("SecurityRiskAssessment", fields)
    product = load("app_products", body["app_product_id"])

    row = db.new_row(TABLE, {
        "app_product_id": product["id"],
        "assessment_label": body["assessment_label"],
        "admin_control_score": body["admin_control_score"],
        "technical_control_score": body["technical_control_score"],
        "physical_control_score": body["physical_control_score"],
        "vendor_oversight_score": body["vendor_oversight_score"],
        "documented_gap_count": body["documented_gap_count"],
        "remediation_plan_present": bool(body.get("remediation_plan_present", False)),
        "residual_risk_score": 0.0,
        "risk_tier": "LOW",
        "state": "DRAFT",
        "finalized_at": None,
    })
    _rescore(row)
    return response.created(db.serialize(row))


@bp.get("")
def list_assessments():
    require(STAFF)
    rows = filter_rows(TABLE, {"app_product_id": "app_product_id", "state": "state",
                               "risk_tier": "risk_tier"})
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_assessment(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(TABLE, row_id)))


@bp.patch("/<row_id>")
def patch_assessment(row_id):
    require("SecurityEngineer")
    row = load(TABLE, row_id)
    body = supplied("SecurityRiskAssessment", _PATCH)
    check_state(row, TABLE, ("DRAFT",))
    for key, value in body.items():
        row[key] = value
    _rescore(row)
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/finalize")
def finalize(row_id):
    require("SecurityEngineer")
    row = load(TABLE, row_id)
    no_body("SecurityRiskAssessment")
    check_state(row, TABLE, ("DRAFT",))

    # check 27.
    approved = [a for a in db.db.applicability_assessments.values()
                if a.get("app_product_id") == row["app_product_id"]
                and a.get("state") == "APPROVED"]
    if not approved:
        fail("ERR_ASSESSMENT_NOT_APPROVED")

    # check 47.
    if row.get("risk_tier") in ("HIGH", "CRITICAL") and not row.get("remediation_plan_present"):
        fail("ERR_REMEDIATION_PLAN_REQUIRED")

    row["state"] = "FINALIZED"
    row["finalized_at"] = clock.now()
    db.touch(row)
    posture.refresh_security_program_state(db.get("app_products", row["app_product_id"]))
    return response.ok(db.serialize(row))
