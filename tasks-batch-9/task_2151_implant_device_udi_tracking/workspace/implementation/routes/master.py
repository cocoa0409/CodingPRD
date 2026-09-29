"""Logical clock, vendors, consignment agreements and the device catalog."""
from flask import Blueprint

import serialize
from auth import ALL_ROLES, INVENTORY_LEAD, endpoint
from envelope import array_response, object_response
from errors import ApiError
from resolve import must
from store import base_record, clock_iso, db, ordered, touch
from validation import (
    apply_page,
    body,
    filter_enum,
    filter_value,
    opt_bool_default,
    opt_int,
    pagination,
    req_dt,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("master", __name__)


# ------------------------------------------------------------ logical clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(ALL_ROLES)
def set_clock():
    data = body()
    raw = req_str(data, "to_iso8601")
    parsed = req_dt(data, "to_iso8601")
    db.set_clock(parsed, raw)
    return object_response({"current_utc": clock_iso()}, 200)


# ------------------------------------------------------------------ vendors
@bp.route("/udi/vendors", methods=["POST"])
@endpoint([INVENTORY_LEAD])
def create_vendor():
    data = body()
    name = req_str(data, "name")
    vendor_code = req_str(data, "vendor_code")
    for existing in db.vendors.values():
        if existing["vendor_code"] == vendor_code:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "vendor_code already exists.")
    record = base_record()
    record.update(
        {
            "name": name,
            "vendor_code": vendor_code,
            "standing": "ACTIVE",
            "open_consignment_liability_cents": 0,
            "recall_open_count": 0,
        }
    )
    db.vendors[record["id"]] = record
    return object_response(serialize.vendor(record), 201)


@bp.route("/udi/vendors/<vendor_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_vendor(vendor_id):
    return object_response(serialize.vendor(must("vendor_id", vendor_id)))


@bp.route("/udi/vendors", methods=["GET"])
@endpoint(ALL_ROLES)
def list_vendors():
    limit, offset = pagination()
    standing = filter_enum("standing", ("ACTIVE", "HOLD"))
    rows = [v for v in db.vendors.values() if standing is None or v["standing"] == standing]
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.vendor(v) for v in page], limit, offset, total)


# ---------------------------------------------------- consignment agreements
@bp.route("/udi/consignment-agreements", methods=["POST"])
@endpoint([INVENTORY_LEAD])
def create_agreement():
    data = body()
    vendor_id = req_str(data, "vendor_id")
    agreement_code = req_str(data, "agreement_code")
    billing_trigger = req_enum(data, "billing_trigger", ("ON_IMPLANT", "ON_RECEIPT"))
    reconciliation_method = req_enum(data, "reconciliation_method", ("UNIT_MATCH", "PERIOD_TRUEUP"))
    period_start = req_dt(data, "period_start_utc")
    period_end = req_dt(data, "period_end_utc")
    tolerance = opt_int(data, "invoice_tolerance_bps", 150, 0, 10000)
    replenishment = opt_int(data, "replenishment_days", 14)

    vendor = must("vendor_id", vendor_id)

    for existing in db.agreements.values():
        if existing["vendor_id"] == vendor["id"] and existing["agreement_code"] == agreement_code:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "agreement_code already exists for vendor.")

    record = base_record()
    record.update(
        {
            "vendor_id": vendor["id"],
            "agreement_code": agreement_code,
            "status": "DRAFT",
            "billing_trigger": billing_trigger,
            "reconciliation_method": reconciliation_method,
            "invoice_tolerance_bps": tolerance,
            "price_list_version": 1,
            "period_start_utc": data["period_start_utc"],
            "period_end_utc": data["period_end_utc"],
            "replenishment_days": replenishment,
        }
    )
    # normalise the stored instants so comparisons never depend on formatting
    record["_period_start"] = period_start
    record["_period_end"] = period_end
    db.agreements[record["id"]] = record
    return object_response(serialize.agreement(record), 201)


@bp.route("/udi/consignment-agreements/<agreement_id>/activate", methods=["POST"])
@endpoint([INVENTORY_LEAD])
def activate_agreement(agreement_id):
    agreement = must("agreement_id", agreement_id)
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "Only a DRAFT agreement can be activated.")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return object_response(serialize.agreement(agreement))


@bp.route("/udi/consignment-agreements/<agreement_id>/price-list-revisions", methods=["POST"])
@endpoint([INVENTORY_LEAD])
def revise_price_list(agreement_id):
    agreement = must("agreement_id", agreement_id)
    if agreement["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_LIFECYCLE_STATE", "Only an ACTIVE agreement can take a price-list revision."
        )
    agreement["price_list_version"] = agreement["price_list_version"] + 1
    touch(agreement)
    return object_response(serialize.agreement(agreement))


@bp.route("/udi/consignment-agreements/<agreement_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_agreement(agreement_id):
    return object_response(serialize.agreement(must("agreement_id", agreement_id)))


@bp.route("/udi/consignment-agreements", methods=["GET"])
@endpoint(ALL_ROLES)
def list_agreements():
    limit, offset = pagination()
    vendor_id = filter_value("vendor_id")
    status = filter_enum("status", ("DRAFT", "ACTIVE", "EXPIRED"))
    rows = []
    for row in db.agreements.values():
        if vendor_id is not None and row["vendor_id"] != vendor_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.agreement(r) for r in page], limit, offset, total)


# ------------------------------------------------------------ catalog items
@bp.route("/udi/catalog-items", methods=["POST"])
@endpoint([INVENTORY_LEAD])
def create_catalog_item():
    data = body()
    vendor_id = req_str(data, "vendor_id")
    device_identifier = req_str(data, "device_identifier")
    description = req_str(data, "description")
    category = req_enum(data, "category", ("HIGH_COST_IMPLANT", "STANDARD_IMPLANT", "ACCESSORY"))
    list_charge_cents = req_int(data, "list_charge_cents", 1)
    charge_code = req_str(data, "charge_code")
    shelf_life_days = req_int(data, "shelf_life_days")
    registry_required = opt_bool_default(data, "registry_required", False)

    vendor = must("vendor_id", vendor_id)

    for existing in db.catalog_items.values():
        if existing["device_identifier"] == device_identifier:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "device_identifier already exists.")

    record = base_record()
    record.update(
        {
            "vendor_id": vendor["id"],
            "device_identifier": device_identifier,
            "description": description,
            "category": category,
            "list_charge_cents": list_charge_cents,
            "charge_code": charge_code,
            "registry_required": registry_required,
            "shelf_life_days": shelf_life_days,
            "on_hand_available_qty": 0,
        }
    )
    db.catalog_items[record["id"]] = record
    return object_response(serialize.catalog_item(record), 201)


@bp.route("/udi/catalog-items/<catalog_item_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_catalog_item(catalog_item_id):
    return object_response(serialize.catalog_item(must("catalog_item_id", catalog_item_id)))


@bp.route("/udi/catalog-items", methods=["GET"])
@endpoint(ALL_ROLES)
def list_catalog_items():
    limit, offset = pagination()
    vendor_id = filter_value("vendor_id")
    category = filter_enum("category", ("HIGH_COST_IMPLANT", "STANDARD_IMPLANT", "ACCESSORY"))
    rows = []
    for row in db.catalog_items.values():
        if vendor_id is not None and row["vendor_id"] != vendor_id:
            continue
        if category is not None and row["category"] != category:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.catalog_item(r) for r in page], limit, offset, total)
