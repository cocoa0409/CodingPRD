"""App products and the compliance-summary read (PRD 3.1, 2.11)."""

from flask import Blueprint

import db
import response
import validators as V
from middleware import STAFF, require
from routes.common import filter_rows, load
from services.calc import small_business_flag
from validators import F, parse, supplied

bp = Blueprint("products", __name__, url_prefix="/health-data/app-products")

_CREATE = {
    "product_name": F("string"),
    "company_legal_name": F("string"),
    "primary_state_code": F("enum", members=V.STATE_CODES),
    "consumer_count": F("int", minimum=0),
    "annual_revenue_cents": F("int", minimum=0),
    "hipaa_covered_transaction_ratio": F("number", minimum=0, maximum=1),
}

_PATCH = {
    "product_name": F("string", required=False),
    "consumer_count": F("int", required=False, minimum=0),
    "annual_revenue_cents": F("int", required=False, minimum=0),
    "hipaa_covered_transaction_ratio": F("number", required=False, minimum=0, maximum=1),
}


@bp.post("")
def create_product():
    require("PlatformAdmin")
    body = parse("AppProduct", _CREATE)
    fields = dict(body)
    fields["hipaa_covered_transaction_ratio"] = V.quantize_ratio(
        body["hipaa_covered_transaction_ratio"])
    row = db.new_row("app_products", {
        "product_name": fields["product_name"],
        "company_legal_name": fields["company_legal_name"],
        "primary_state_code": fields["primary_state_code"],
        "consumer_count": fields["consumer_count"],
        "annual_revenue_cents": fields["annual_revenue_cents"],
        "hipaa_covered_transaction_ratio": fields["hipaa_covered_transaction_ratio"],
        "small_business_flag": False,
        "applicability_status": "UNDETERMINED",
        "regulated_scope": "NONE",
        "active_element_count": 0,
        "regulated_element_count": 0,
        "compliance_deadline_date": None,
        "active_share_consent_count": 0,
        "exposure_cents": 0,
        "policy_compliance_state": "NO_POLICY",
        "security_program_state": "NONE",
    })
    row["small_business_flag"] = small_business_flag(row)
    return response.created(db.serialize(row))


@bp.get("")
def list_products():
    require(STAFF)
    rows = filter_rows("app_products", {"applicability_status": "applicability_status"})
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_product(row_id):
    require(STAFF)
    row = load("app_products", row_id)
    return response.ok(db.serialize(row))


@bp.patch("/<row_id>")
def patch_product(row_id):
    require("PlatformAdmin")
    row = load("app_products", row_id)
    body = supplied("AppProduct", _PATCH)
    for key, value in body.items():
        if key == "hipaa_covered_transaction_ratio":
            value = V.quantize_ratio(value)
        row[key] = value
    row["small_business_flag"] = small_business_flag(row)
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.get("/<row_id>/compliance-summary")
def compliance_summary(row_id):
    require(STAFF)
    product = load("app_products", row_id)
    consumer_ids = set(c["id"] for c in db.db.consumers.values()
                       if c.get("app_product_id") == product["id"])
    open_requests = [r for r in db.db.consumer_requests.values()
                     if r.get("consumer_id") in consumer_ids
                     and r.get("state") not in ("FULFILLED", "DENIED")]
    request_ids = set(r["id"] for r in db.db.consumer_requests.values()
                      if r.get("consumer_id") in consumer_ids)
    outstanding = [t for t in db.db.deletion_tasks.values()
                   if t.get("consumer_request_id") in request_ids
                   and t.get("state") in ("PENDING", "NOTIFIED", "FAILED")]
    return response.ok({
        "app_product_id": product["id"],
        "applicability_status": product["applicability_status"],
        "regulated_scope": product["regulated_scope"],
        "active_element_count": product["active_element_count"],
        "regulated_element_count": product["regulated_element_count"],
        "active_share_consent_count": product["active_share_consent_count"],
        "policy_compliance_state": product["policy_compliance_state"],
        "security_program_state": product["security_program_state"],
        "exposure_cents": product["exposure_cents"],
        "open_request_count": len(open_requests),
        "outstanding_deletion_task_count": len(outstanding),
    })
