"""Vendor endpoints (PRD 3.1)."""

from flask import Blueprint

import db
import guards
import response

bp = Blueprint("vendors", __name__)

VENDOR_TYPES = ("TPA", "PBM", "BROKER", "CONSULTANT", "NETWORK_VENDOR")


@bp.route("/compliance/vendors", methods=["POST"])
def create_vendor():
    guards.authorize("PlanSponsorAdmin")
    body = guards.read_body()
    legal_name = guards.field(body, "legal_name", "string")
    vendor_type = guards.field(body, "vendor_type", "enum", enum=VENDOR_TYPES)
    contact_email = guards.field(body, "contact_email", "string")
    record = db.common_fields()
    record.update({
        "legal_name": legal_name,
        "vendor_type": vendor_type,
        "contact_email": contact_email,
    })
    db.vendors[record["id"]] = record
    return response.created_response(response.public(record))


@bp.route("/compliance/vendors/<row_id>", methods=["GET"])
def get_vendor(row_id):
    role = guards.authorize(
        "PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor", "VendorContact"
    )[1]
    vendor = guards.fetch("vendor", row_id)
    guards.vendor_identity(role, guards.caller_id())
    return response.object_response(response.public(vendor))


@bp.route("/compliance/vendors", methods=["GET"])
def list_vendors():
    guards.authorize("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")
    limit, offset = guards.pagination()
    rows = guards.apply_filters(db.ordered(db.vendors), [
        ("vendor_type", "vendor_type", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )
