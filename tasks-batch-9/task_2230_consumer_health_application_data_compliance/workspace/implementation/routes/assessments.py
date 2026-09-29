"""Applicability assessments (PRD 3.1)."""

from flask import Blueprint

import constants as K
import db
import response
import validators as V
from errors import fail
from middleware import STAFF, require
from routes.common import check_state, filter_rows, load
from services.calc import applicability_determination
from validators import F, no_body, parse

bp = Blueprint("assessments", __name__, url_prefix="/health-data/applicability-assessments")

TABLE = "applicability_assessments"


@bp.post("")
def create_assessment():
    require("PrivacyOfficer")
    body = parse("ApplicabilityAssessment", {
        "app_product_id": F("string"),
        "entity_status_claim": F("enum", members=V.ENTITY_STATUS_CLAIMS),
        "analyst_note": F("string"),
    })
    load("app_products", body["app_product_id"])
    row = db.new_row(TABLE, {
        "app_product_id": body["app_product_id"],
        "entity_status_claim": body["entity_status_claim"],
        "analyst_note": body["analyst_note"],
        "determination": None,
        "regulated_element_count_snapshot": 0,
        "active_element_count_snapshot": 0,
        "regulated_scope": None,
        "compliance_deadline_date": None,
        "state": "DRAFT",
        "revision_count": 0,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "return_reason": None,
    })
    return response.created(db.serialize(row))


@bp.get("")
def list_assessments():
    require(STAFF)
    rows = filter_rows(TABLE, {"app_product_id": "app_product_id", "state": "state"})
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_assessment(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(TABLE, row_id)))


@bp.post("/<row_id>/submit")
def submit_assessment(row_id):
    user_id, _ = require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("ApplicabilityAssessment")
    check_state(row, TABLE, ("DRAFT",))
    product = load("app_products", row["app_product_id"])

    active = [e for e in db.db.data_elements.values()
              if e.get("app_product_id") == product["id"] and e.get("status") == "ACTIVE"]
    if not active:
        fail("ERR_NO_ACTIVE_ELEMENTS")

    result = applicability_determination(row, product)
    db.set_fields(product, small_business_flag=result["small_business_flag"])
    row["state"] = "SUBMITTED"
    row["determination"] = result["determination"]
    row["active_element_count_snapshot"] = result["active_element_count_snapshot"]
    row["regulated_element_count_snapshot"] = result["regulated_element_count_snapshot"]
    row["regulated_scope"] = result["regulated_scope"]
    row["compliance_deadline_date"] = result["compliance_deadline_date"]
    row["submitted_by_user_id"] = user_id
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/approve")
def approve_assessment(row_id):
    user_id, _ = require("ComplianceApprover")
    row = load(TABLE, row_id)
    no_body("ApplicabilityAssessment")
    check_state(row, TABLE, ("SUBMITTED",))
    if user_id == row.get("submitted_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES")

    product = load("app_products", row["app_product_id"])
    row["state"] = "APPROVED"
    row["approved_by_user_id"] = user_id
    db.touch(row)

    for other in db.rows_of(TABLE):
        if other["id"] != row["id"] and other.get("app_product_id") == row["app_product_id"] \
                and other.get("state") == "APPROVED":
            other["state"] = "SUPERSEDED"
            db.touch(other)

    product["applicability_status"] = row["determination"]
    product["regulated_scope"] = row["regulated_scope"]
    product["compliance_deadline_date"] = row["compliance_deadline_date"]
    db.touch(product)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/return")
def return_assessment(row_id):
    require("ComplianceApprover")
    row = load(TABLE, row_id)
    body = parse("ApplicabilityAssessment", {"return_reason": F("string")},
                 extra_allowed=("return_reason",))
    check_state(row, TABLE, ("SUBMITTED",))
    row["state"] = "RETURNED"
    row["return_reason"] = body["return_reason"]
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/revise")
def revise_assessment(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("ApplicabilityAssessment")
    check_state(row, TABLE, ("RETURNED",))
    if row.get("revision_count", 0) >= K.MAX_ASSESSMENT_REVISIONS:
        fail("ERR_ASSESSMENT_REVISION_LIMIT")
    row["state"] = "DRAFT"
    row["revision_count"] = row.get("revision_count", 0) + 1
    row["determination"] = None
    row["regulated_scope"] = None
    row["compliance_deadline_date"] = None
    row["submitted_by_user_id"] = None
    db.touch(row)
    return response.ok(db.serialize(row))
