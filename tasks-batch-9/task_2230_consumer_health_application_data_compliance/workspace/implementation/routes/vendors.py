"""Vendors, their agreement posture and the termination cascade (PRD 3.4)."""

from flask import Blueprint

import clock
import db
import response
import validators as V
from errors import fail
from middleware import STAFF, require
from routes.common import check_state, filter_rows, load
from services.cascade import terminate_vendor
from validators import F, no_body, parse, supplied

bp = Blueprint("vendors", __name__, url_prefix="/health-data/vendors")

TABLE = "vendors"

_CLAUSES = {
    "flow_down_clause": F("bool", required=False),
    "audit_rights_clause": F("bool", required=False),
    "sale_authorization_clause": F("bool", required=False),
    "deletion_sla_days": F("int", required=False, minimum=1, maximum=90),
}


def agreement_compliance(row):
    """consent_posture_derivation STEP 2."""
    if not row.get("flow_down_clause") or not row.get("audit_rights_clause"):
        return "DEFICIENT"
    if row.get("vendor_kind") == "PURCHASER" and not row.get("sale_authorization_clause"):
        return "DEFICIENT"
    return "COMPLIANT"


@bp.post("")
def create_vendor():
    require("PrivacyOfficer")
    fields = {
        "app_product_id": F("string"),
        "vendor_name": F("string"),
        "vendor_kind": F("enum", members=V.VENDOR_KINDS),
        "subprocessor_of_id": F("string", required=False, nullable=True),
    }
    fields.update(_CLAUSES)
    body = parse("Vendor", fields)

    product = load("app_products", body["app_product_id"])
    parent_id = body.get("subprocessor_of_id")
    parent = load(TABLE, parent_id) if parent_id is not None else None

    # check 6.
    if parent is not None and parent.get("app_product_id") != product["id"]:
        fail("ERR_CROSS_PRODUCT_REFERENCE")

    # check 18.
    for other in db.rows_of(TABLE):
        if other.get("app_product_id") == product["id"] \
                and other.get("vendor_name") == body["vendor_name"]:
            fail("ERR_DUPLICATE_VENDOR_NAME")

    row = db.new_row(TABLE, {
        "app_product_id": product["id"],
        "vendor_name": body["vendor_name"],
        "vendor_kind": body["vendor_kind"],
        "subprocessor_of_id": parent_id,
        "flow_down_clause": bool(body.get("flow_down_clause", False)),
        "audit_rights_clause": bool(body.get("audit_rights_clause", False)),
        "sale_authorization_clause": bool(body.get("sale_authorization_clause", False)),
        "deletion_sla_days": body.get("deletion_sla_days", 30),
        "agreement_state": "DRAFT",
        "agreement_compliance": "DEFICIENT",
        "executed_at": None,
        "terminated_at": None,
    })
    row["agreement_compliance"] = agreement_compliance(row)
    return response.created(db.serialize(row))


@bp.get("")
def list_vendors():
    require(STAFF)
    rows = filter_rows(TABLE, {"app_product_id": "app_product_id",
                               "subprocessor_of_id": "subprocessor_of_id",
                               "agreement_state": "agreement_state"})
    return response.paginate(rows, db.serialize)


@bp.get("/<row_id>")
def read_vendor(row_id):
    require(STAFF)
    return response.ok(db.serialize(load(TABLE, row_id)))


@bp.patch("/<row_id>")
def patch_vendor(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    body = supplied("Vendor", _CLAUSES)
    check_state(row, TABLE, ("DRAFT",), field="agreement_state")
    for key, value in body.items():
        row[key] = value
    row["agreement_compliance"] = agreement_compliance(row)
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/execute-agreement")
def execute_agreement(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("Vendor")
    check_state(row, TABLE, ("DRAFT",), field="agreement_state")

    # checks 31, 32 and 33.
    if not row.get("flow_down_clause"):
        fail("ERR_FLOW_DOWN_CLAUSE_MISSING")
    if not row.get("audit_rights_clause"):
        fail("ERR_AUDIT_RIGHTS_MISSING")
    parent_id = row.get("subprocessor_of_id")
    if parent_id is not None:
        parent = db.get(TABLE, parent_id)
        if parent is None or parent.get("agreement_state") != "EXECUTED":
            fail("ERR_SUBPROCESSOR_PARENT_NOT_EXECUTED")

    row["agreement_state"] = "EXECUTED"
    row["executed_at"] = clock.now()
    row["agreement_compliance"] = agreement_compliance(row)
    db.touch(row)
    return response.ok(db.serialize(row))


@bp.post("/<row_id>/terminate-agreement")
def terminate_agreement(row_id):
    require("PrivacyOfficer")
    row = load(TABLE, row_id)
    no_body("Vendor")
    check_state(row, TABLE, ("EXECUTED",), field="agreement_state")
    terminate_vendor(row)
    return response.ok(db.serialize(row))
