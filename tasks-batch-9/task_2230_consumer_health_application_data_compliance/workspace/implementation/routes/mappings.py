"""Element-purpose mappings (PRD 3.2)."""

from flask import Blueprint

import db
import response
import validators as V
from errors import fail
from middleware import STAFF, require
from routes.common import check_state, filter_rows, load
from services import posture
from services.calc import REGULATED_CLASSES
from validators import F, no_body, parse

bp = Blueprint("mappings", __name__, url_prefix="/health-data/element-purpose-mappings")

TABLE = "element_purpose_mappings"


def _regulated(element):
    return element.get("chd_classification") in REGULATED_CLASSES


@bp.post("")
def create_mapping():
    require("DataSteward")
    body = parse("ElementPurposeMapping", {
        "data_element_id": F("string"),
        "processing_purpose_id": F("string"),
        "vendor_id": F("string", required=False, nullable=True),
        "disclosure_specificity": F("enum", members=V.DISCLOSURE_SPECIFICITIES),
    })

    # check 5, in the declared field order.
    element = load("data_elements", body["data_element_id"])
    purpose = load("processing_purposes", body["processing_purpose_id"])
    vendor_id = body.get("vendor_id")
    vendor = load("vendors", vendor_id) if vendor_id is not None else None

    # check 6.
    product_id = element.get("app_product_id")
    if purpose.get("app_product_id") != product_id:
        fail("ERR_CROSS_PRODUCT_REFERENCE")
    if vendor is not None and vendor.get("app_product_id") != product_id:
        fail("ERR_CROSS_PRODUCT_REFERENCE")

    # check 29.
    if purpose.get("third_party_disclosure_required") and vendor_id is None:
        fail("ERR_VENDOR_REQUIRED_FOR_DISCLOSURE")

    row = db.new_row(TABLE, {
        "data_element_id": element["id"],
        "processing_purpose_id": purpose["id"],
        "vendor_id": vendor_id,
        "disclosure_specificity": body["disclosure_specificity"],
        "status": "PROPOSED",
        "suspension_reason": None,
        "regulated_flag": _regulated(element),
    })
    return response.created(db.serialize(row))


@bp.get("")
def list_mappings():
    require(STAFF)
    rows = filter_rows(TABLE, {
        "data_element_id": "data_element_id",
        "processing_purpose_id": "processing_purpose_id",
        "vendor_id": "vendor_id",
        "status": "status",
    })
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_mapping(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(TABLE, row_id)))


@bp.post("/<row_id>/activate")
def activate(row_id):
    require("DataSteward")
    row = load(TABLE, row_id)
    no_body("ElementPurposeMapping")
    previous = row.get("status")
    check_state(row, TABLE, ("PROPOSED", "SUSPENDED"), field="status")

    element = load("data_elements", row["data_element_id"])
    if element.get("status") != "ACTIVE":
        fail("ERR_ELEMENT_RETIRED")

    product = posture.product_of_mapping(row)
    purpose = db.get("processing_purposes", row.get("processing_purpose_id"))

    # check 28.
    if product is None or product.get("applicability_status") not in ("DUAL_TRACK", "CHD_REGULATED"):
        fail("ERR_APPLICABILITY_UNDETERMINED")

    if purpose is not None and purpose.get("third_party_disclosure_required"):
        # check 29.
        if row.get("vendor_id") is None:
            fail("ERR_VENDOR_REQUIRED_FOR_DISCLOSURE")
        # check 30.
        vendor = db.get("vendors", row.get("vendor_id"))
        if vendor is None or vendor.get("agreement_state") != "EXECUTED" \
                or vendor.get("agreement_compliance") != "COMPLIANT":
            fail("ERR_VENDOR_AGREEMENT_DEFICIENT")

    # check 34.
    if product.get("policy_compliance_state") == "LAPSED":
        fail("ERR_POLICY_LAPSED")

    row["status"] = "ACTIVE"
    if previous == "PROPOSED":
        row["regulated_flag"] = _regulated(element)
    else:
        row["suspension_reason"] = None
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/suspend")
def suspend(row_id):
    require("DataSteward")
    row = load(TABLE, row_id)
    body = parse("ElementPurposeMapping", {"suspension_reason": F("string")},
                 extra_allowed=("suspension_reason",))
    check_state(row, TABLE, ("ACTIVE",), field="status")
    row["status"] = "SUSPENDED"
    row["suspension_reason"] = body["suspension_reason"]
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/retire")
def retire(row_id):
    require("DataSteward")
    row = load(TABLE, row_id)
    body = parse("ElementPurposeMapping",
                 {"suspension_reason": F("string", required=False)},
                 extra_allowed=("suspension_reason",))
    check_state(row, TABLE, ("PROPOSED", "ACTIVE", "SUSPENDED"), field="status")
    row["status"] = "RETIRED"
    if "suspension_reason" in body:
        row["suspension_reason"] = body["suspension_reason"]
    db.touch(row)
    posture.recount_regulated_elements(posture.product_of_mapping(row))
    return response.ok(db.serialize(row))
