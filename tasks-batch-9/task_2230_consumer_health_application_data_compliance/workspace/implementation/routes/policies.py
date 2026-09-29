"""Privacy policy versions (PRD 3.3)."""

from flask import Blueprint

import clock
import constants as K
import db
import response
import validators as V
from errors import fail
from middleware import STAFF, require
from routes.common import check_state, filter_rows, load
from services.calc import policy_completeness_score
from validators import F, no_body, parse

bp = Blueprint("policies", __name__, url_prefix="/health-data/privacy-policy-versions")

TABLE = "privacy_policy_versions"

_SUPERSEDABLE = ("PUBLISHED", "SUPERSEDED_PENDING_UPDATE")


@bp.post("")
def create_policy():
    user_id, _ = require("PrivacyOfficer")
    body = parse("PrivacyPolicyVersion", {
        "app_product_id": F("string"),
        "applicability_assessment_id": F("string"),
        "version_label": F("string"),
        "specificity_mode": F("enum", members=V.SPECIFICITY_MODES),
        "disclosed_category_count": F("int", minimum=0),
        "disclosed_purpose_count": F("int", minimum=0),
        "disclosed_third_party_count": F("int", minimum=0),
        "named_third_party_count": F("int", minimum=0),
        "effective_from": F("date"),
        "expected_app_product_version": F("int"),
    }, extra_allowed=("expected_app_product_version",))

    product = load("app_products", body["app_product_id"])
    assessment = load("applicability_assessments", body["applicability_assessment_id"])

    # check 6.
    if assessment.get("app_product_id") != product["id"]:
        fail("ERR_CROSS_PRODUCT_REFERENCE")

    # check 9.
    if body["expected_app_product_version"] != product.get("version"):
        fail("ERR_STALE_PRODUCT_VERSION")

    if body["named_third_party_count"] > body["disclosed_third_party_count"]:
        fail("ERR_INVALID_REQUEST",
             "named_third_party_count may not exceed disclosed_third_party_count.")

    row = db.new_row(TABLE, {
        "app_product_id": product["id"],
        "applicability_assessment_id": assessment["id"],
        "version_label": body["version_label"],
        "specificity_mode": body["specificity_mode"],
        "disclosed_category_count": body["disclosed_category_count"],
        "disclosed_purpose_count": body["disclosed_purpose_count"],
        "disclosed_third_party_count": body["disclosed_third_party_count"],
        "named_third_party_count": body["named_third_party_count"],
        "effective_from": body["effective_from"],
        "effective_to": None,
        "completeness_score": 0.0,
        "gap_count": 0,
        "state": "DRAFT",
        "authored_by_user_id": user_id,
        "published_by_user_id": None,
    })
    db.touch(product)
    return response.created(db.serialize(row))


@bp.get("")
def list_policies():
    require(STAFF)
    rows = filter_rows(TABLE, {
        "app_product_id": "app_product_id",
        "applicability_assessment_id": "applicability_assessment_id",
        "state": "state",
    })
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_policy(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(TABLE, row_id)))


@bp.post("/<row_id>/submit-review")
def submit_review(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("PrivacyPolicyVersion")
    check_state(row, TABLE, ("DRAFT",))

    assessment = load("applicability_assessments", row["applicability_assessment_id"])
    # check 27.
    if assessment.get("state") != "APPROVED":
        fail("ERR_ASSESSMENT_NOT_APPROVED")

    product = load("app_products", row["app_product_id"])
    score, gaps = policy_completeness_score(row, product)
    row["state"] = "IN_REVIEW"
    row["completeness_score"] = score
    row["gap_count"] = gaps
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/return-to-draft")
def return_to_draft(row_id):
    require("ComplianceApprover")
    row = load(TABLE, row_id)
    body = parse("PrivacyPolicyVersion", {"return_reason": F("string")},
                 extra_allowed=("return_reason",))
    check_state(row, TABLE, ("IN_REVIEW",), specific="ERR_POLICY_NOT_IN_REVIEW")
    row["state"] = "DRAFT"
    row["completeness_score"] = 0.0
    row["gap_count"] = 0
    db.touch(row)
    _ = body
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/publish")
def publish(row_id):
    user_id, _ = require("ComplianceApprover")
    row = load(TABLE, row_id)
    no_body("PrivacyPolicyVersion")
    check_state(row, TABLE, ("IN_REVIEW",), specific="ERR_POLICY_NOT_IN_REVIEW")

    # check 10: the publisher may not be the author.
    if user_id == row.get("authored_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES")

    effective_from = row["effective_from"]
    # check 35.
    if effective_from < clock.today():
        fail("ERR_EFFECTIVE_DATE_IN_PAST")

    # check 36: half-open [effective_from, effective_to) of every other seated version.
    for other in db.rows_of(TABLE):
        if other["id"] == row["id"] or other.get("app_product_id") != row["app_product_id"]:
            continue
        if other.get("state") not in ("PUBLISHED", "SUPERSEDED_PENDING_UPDATE", "SUPERSEDED"):
            continue
        start = other.get("effective_from")
        end = other.get("effective_to")
        if start is None or effective_from < start:
            continue
        if end is None or effective_from < end:
            fail("ERR_POLICY_WINDOW_OVERLAP")

    # check 46.
    if row.get("completeness_score", 0.0) < K.POLICY_PUBLISH_THRESHOLD:
        fail("ERR_POLICY_COMPLETENESS_BELOW_THRESHOLD")

    row["state"] = "PUBLISHED"
    row["published_by_user_id"] = user_id
    db.touch(row)

    for other in db.rows_of(TABLE):
        if other["id"] == row["id"] or other.get("app_product_id") != row["app_product_id"]:
            continue
        if other.get("state") in _SUPERSEDABLE:
            other["state"] = "SUPERSEDED"
            other["effective_to"] = effective_from
            db.touch(other)

    product = load("app_products", row["app_product_id"])
    db.set_fields(product, policy_compliance_state="CURRENT")
    return response.ok(db.serialize(row))
