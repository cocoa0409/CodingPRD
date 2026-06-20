"""VendorBill lifecycle (PRD §3.4)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success, list_success
from services.common import (
    get_json_body, require_fields, serialize,
    pagination_params, paginate, sort_by_creation,
)
from services.calculations import vendor_recoverable

vendor_bills_bp = Blueprint("vendor_bills", __name__)


@vendor_bills_bp.route("/vendor-bills", methods=["POST"])
@require_roles("PropertyManager")
def create_vendor_bill():
    body = get_json_body()
    require_fields(body, "property_id", "utility_id", "period_label", "total_cost_cents")

    property_id = body["property_id"]
    if property_id not in db.properties:
        raise ApiError("ERR_NOT_FOUND", "Property not found")
    utility_id = body["utility_id"]
    if utility_id not in db.utilities:
        raise ApiError("ERR_NOT_FOUND", "Utility not found")

    period_label = body["period_label"]
    if not isinstance(period_label, str) or not period_label.strip():
        raise ApiError("ERR_INVALID_REQUEST", "period_label must be a non-empty string")

    total_cost_cents = body["total_cost_cents"]
    if (not isinstance(total_cost_cents, int) or isinstance(total_cost_cents, bool)
            or total_cost_cents <= 0):
        raise ApiError("ERR_INVALID_REQUEST", "total_cost_cents must be > 0")

    record = {
        "property_id": property_id,
        "utility_id": utility_id,
        "period_label": period_label,
        "total_cost_cents": total_cost_cents,
        "common_area_cents": 0,
        "cap_cents": 0,
        "recoverable_cents": 0,
        "status": "RECEIVED",
    }
    db.stamp_create(record)
    db.vendor_bills[record["id"]] = record
    return success(serialize(record), status=201)


@vendor_bills_bp.route("/vendor-bills/<vendor_bill_id>", methods=["GET"])
@require_roles("PropertyManager", "Auditor")
def get_vendor_bill(vendor_bill_id):
    record = db.vendor_bills.get(vendor_bill_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", "VendorBill not found")
    return success(serialize(record), status=200)


@vendor_bills_bp.route("/vendor-bills", methods=["GET"])
@require_roles("PropertyManager", "Auditor")
def list_vendor_bills():
    property_id = request.args.get("property_id")
    utility_id = request.args.get("utility_id")
    period_label = request.args.get("period_label")
    status = request.args.get("status")
    items = list(db.vendor_bills.values())
    if property_id is not None:
        items = [v for v in items if v["property_id"] == property_id]
    if utility_id is not None:
        items = [v for v in items if v["utility_id"] == utility_id]
    if period_label is not None:
        items = [v for v in items if v["period_label"] == period_label]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_by_creation(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return list_success([serialize(v) for v in page], limit, offset, total)


@vendor_bills_bp.route("/vendor-bills/<vendor_bill_id>/approve", methods=["POST"])
@require_roles("PropertyManager")
def approve_vendor_bill(vendor_bill_id):
    vb = db.vendor_bills.get(vendor_bill_id)
    if vb is None:
        raise ApiError("ERR_NOT_FOUND", "VendorBill not found")
    if vb["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "VendorBill is not RECEIVED")
    if vb["total_cost_cents"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "total_cost_cents must be > 0")

    prop = db.properties[vb["property_id"]]
    common_area_cents, cap_cents, recoverable_cents = vendor_recoverable(
        vb["total_cost_cents"], prop["common_area_pct"], prop["recovery_cap_pct"]
    )
    vb["common_area_cents"] = common_area_cents
    vb["cap_cents"] = cap_cents
    vb["recoverable_cents"] = recoverable_cents
    vb["status"] = "APPROVED"
    db.touch(vb)
    return success(serialize(vb), status=200)


@vendor_bills_bp.route("/vendor-bills/<vendor_bill_id>/void", methods=["POST"])
@require_roles("PropertyManager")
def void_vendor_bill(vendor_bill_id):
    vb = db.vendor_bills.get(vendor_bill_id)
    if vb is None:
        raise ApiError("ERR_NOT_FOUND", "VendorBill not found")
    if vb["status"] not in ("RECEIVED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", "VendorBill cannot be voided from its current state")

    referencing = [c for c in db.billing_cycles.values()
                   if c["vendor_bill_id"] == vendor_bill_id]
    if vb["status"] == "RECEIVED":
        # Cannot void if any cycle references it in a non-OPEN status.
        for c in referencing:
            if c["status"] != "OPEN":
                raise ApiError("ERR_VENDOR_BILL_IN_USE", "VendorBill in use")
    else:  # APPROVED
        blocking = {"ALLOCATED", "STATEMENTS_ISSUED", "CLOSED"}
        for c in referencing:
            if c["status"] in blocking:
                raise ApiError("ERR_VENDOR_BILL_IN_USE", "VendorBill in use")

    vb["status"] = "VOIDED"
    db.touch(vb)
    return success(serialize(vb), status=200)
