"""Work order intake, condition photos, line items, list/fetch."""
from flask import Blueprint, request

from db import db
from errors import err
import errors
from middleware import get_identity, require_roles
from helpers import (base_record, get_body, require_string, require_number,
                     optional_number, optional_string, optional_bool,
                     require_enum, get_work_order_or_404, get_resource_or_404,
                     get_fk_or_404, parse_pagination, paginate, touch,
                     serialize, serialize_list)
from response import ok_object, ok_array
from services import recompute_line_item_subtotal

bp = Blueprint("work_orders", __name__)

SERVICE_TYPES = {"REUPHOLSTERY", "REFINISH", "REPAIR"}


# --------------------------------------------------------------------------
# Work order intake
# --------------------------------------------------------------------------
@bp.post("/work-orders")
def create_work_order():
    _, role = get_identity()
    require_roles(role, {"IntakeClerk"})
    body = get_body()
    customer_id = require_string(body, "customer_id")
    service_type = require_enum(body, "service_type", SERVICE_TYPES)
    rush = optional_bool(body, "rush_requested", False)
    # FK existence (priority 12)
    get_fk_or_404(db.customers, customer_id)
    rec = base_record(common=True)
    rec.update({
        "customer_id": customer_id,
        "service_type": service_type,
        "rush_requested": rush,
        "promised_turnaround_days": None,
        "estimate_total_cents": 0,
        "final_invoice_cents": 0,
        "amount_paid_cents": 0,
        "balance_due_cents": 0,
        "materials_committed_cents": 0,
        "status": "INTAKE",
        "active_estimate_id": None,
        "completed_at": None,
    })
    db.work_orders[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/work-orders/<wid>")
def get_work_order(wid):
    _, role = get_identity()
    require_roles(role, {"IntakeClerk", "ShopManager", "Estimator", "Customer"})
    rec = get_work_order_or_404(wid)
    return ok_object(serialize(rec), 200)


@bp.get("/work-orders")
def list_work_orders():
    _, role = get_identity()
    require_roles(role, {"IntakeClerk", "ShopManager", "Estimator"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    customer_id = request.args.get("customer_id")
    matches = list(db.work_orders.values())
    if status is not None:
        matches = [w for w in matches if w["status"] == status]
    if customer_id is not None:
        matches = [w for w in matches if w["customer_id"] == customer_id]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


# --------------------------------------------------------------------------
# Condition photos
# --------------------------------------------------------------------------
@bp.post("/condition-photos")
def create_condition_photo():
    _, role = get_identity()
    require_roles(role, {"IntakeClerk"})
    body = get_body()
    work_order_id = require_string(body, "work_order_id")
    image_uri = require_string(body, "image_uri")
    damage_note = optional_string(body, "damage_note", "")
    # FK existence (priority 12)
    get_fk_or_404(db.work_orders, work_order_id)
    rec = base_record(common=False)  # ConditionPhoto: id + created_at only
    rec.update({
        "work_order_id": work_order_id,
        "image_uri": image_uri,
        "damage_note": damage_note,
    })
    db.condition_photos[rec["id"]] = rec
    _assign_sequence_numbers(work_order_id)
    return ok_object(serialize(db.condition_photos[rec["id"]]), 201)


def _assign_sequence_numbers(work_order_id):
    """sequence_no: 1-based intake order by created_at ASC among order's photos."""
    photos = [p for p in db.condition_photos.values()
              if p["work_order_id"] == work_order_id]
    photos.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for idx, p in enumerate(photos, start=1):
        p["sequence_no"] = idx


@bp.get("/condition-photos/<pid>")
def get_condition_photo(pid):
    _, role = get_identity()
    require_roles(role, {"IntakeClerk", "ShopManager", "Estimator", "Customer"})
    rec = get_resource_or_404(db.condition_photos, pid)
    return ok_object(serialize(rec), 200)


@bp.get("/condition-photos")
def list_condition_photos():
    _, role = get_identity()
    require_roles(role, {"IntakeClerk", "ShopManager", "Estimator", "Customer"})
    limit, offset = parse_pagination()
    work_order_id = request.args.get("work_order_id")
    matches = list(db.condition_photos.values())
    if work_order_id is not None:
        matches = [p for p in matches if p["work_order_id"] == work_order_id]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


# --------------------------------------------------------------------------
# Line items
# --------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/line-items")
def create_line_item(wid):
    _, role = get_identity()
    require_roles(role, {"IntakeClerk"})
    wo = get_work_order_or_404(wid)
    body = get_body()
    piece_label = require_string(body, "piece_label")
    labor_hours = require_number(body, "labor_hours")
    yardage_required = require_number(body, "yardage_required")
    board_feet_required = optional_number(body, "board_feet_required", 0)
    fabric_sku_id = body.get("fabric_sku_id")
    foam_spec_id = body.get("foam_spec_id")
    if fabric_sku_id is not None and not isinstance(fabric_sku_id, str):
        raise err(errors.ERR_INVALID_REQUEST, "fabric_sku_id must be a string")
    if foam_spec_id is not None and not isinstance(foam_spec_id, str):
        raise err(errors.ERR_INVALID_REQUEST, "foam_spec_id must be a string")
    if labor_hours <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "labor_hours must be > 0")
    if yardage_required < 0 or board_feet_required < 0:
        raise err(errors.ERR_INVALID_REQUEST, "yardage/board_feet must be >= 0")

    service_type = wo["service_type"]

    # State check (priority 20): first item must advance INTAKE; both INTAKE and
    # ESTIMATING accept new line items.
    if wo["status"] not in ("INTAKE", "ESTIMATING"):
        raise err(errors.ERR_INVALID_STATE,
                  "Line items may only be added during INTAKE or ESTIMATING")

    # FK existence (priority 12): catalog references must exist at all.
    if fabric_sku_id is not None:
        get_fk_or_404(db.fabric_skus, fabric_sku_id)
    if foam_spec_id is not None:
        get_fk_or_404(db.foam_specs, foam_spec_id)

    # Service-type field rules (priority 30).
    if service_type == "REUPHOLSTERY":
        if fabric_sku_id is None or yardage_required <= 0:
            raise err(errors.ERR_LINE_ITEM_FIELDS_INVALID,
                      "REUPHOLSTERY requires fabric_sku_id and yardage_required > 0")
    else:  # REFINISH / REPAIR
        if fabric_sku_id is not None or yardage_required != 0:
            raise err(errors.ERR_LINE_ITEM_FIELDS_INVALID,
                      "REFINISH/REPAIR require no fabric_sku_id and yardage_required == 0")

    # Catalog availability (priority 31): LISTED only; board_feet>0 needs foam.
    if fabric_sku_id is not None:
        sku = db.fabric_skus[fabric_sku_id]
        if sku["status"] != "LISTED":
            raise err(errors.ERR_CATALOG_ITEM_UNAVAILABLE, "Fabric SKU is not LISTED")
    if foam_spec_id is not None:
        spec = db.foam_specs[foam_spec_id]
        if spec["status"] != "LISTED":
            raise err(errors.ERR_CATALOG_ITEM_UNAVAILABLE, "Foam spec is not LISTED")
    if board_feet_required > 0 and foam_spec_id is None:
        raise err(errors.ERR_CATALOG_ITEM_UNAVAILABLE,
                  "board_feet_required > 0 requires a foam_spec_id")

    # First line item requires at least one condition photo and advances status.
    is_first = not any(li["work_order_id"] == wid for li in db.line_items.values())
    if is_first:
        has_photo = any(p["work_order_id"] == wid for p in db.condition_photos.values())
        if not has_photo:
            raise err(errors.ERR_INVALID_STATE,
                      "At least one condition photo is required before the first line item")

    rec = base_record(common=True)
    rec.update({
        "work_order_id": wid,
        "piece_label": piece_label,
        "fabric_sku_id": fabric_sku_id,
        "foam_spec_id": foam_spec_id,
        "yardage_required": yardage_required,
        "board_feet_required": board_feet_required,
        "labor_hours": labor_hours,
        "piece_subtotal_cents": 0,
    })
    recompute_line_item_subtotal(rec, service_type)
    db.line_items[rec["id"]] = rec

    if is_first and wo["status"] == "INTAKE":
        wo["status"] = "ESTIMATING"
        touch(wo)

    return ok_object(serialize(rec), 201)


@bp.get("/work-orders/<wid>/line-items")
def list_work_order_line_items(wid):
    _, role = get_identity()
    require_roles(role, {"IntakeClerk", "ShopManager", "Estimator", "Customer"})
    limit, offset = parse_pagination()
    get_work_order_or_404(wid)
    matches = [li for li in db.line_items.values() if li["work_order_id"] == wid]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.get("/line-items/<lid>")
def get_line_item(lid):
    _, role = get_identity()
    require_roles(role, {"IntakeClerk", "ShopManager", "Estimator", "Customer"})
    rec = get_resource_or_404(db.line_items, lid)
    return ok_object(serialize(rec), 200)


@bp.get("/line-items")
def list_line_items():
    _, role = get_identity()
    require_roles(role, {"IntakeClerk", "ShopManager", "Estimator"})
    limit, offset = parse_pagination()
    work_order_id = request.args.get("work_order_id")
    fabric_sku_id = request.args.get("fabric_sku_id")
    foam_spec_id = request.args.get("foam_spec_id")
    matches = list(db.line_items.values())
    if work_order_id is not None:
        matches = [li for li in matches if li["work_order_id"] == work_order_id]
    if fabric_sku_id is not None:
        matches = [li for li in matches if li.get("fabric_sku_id") == fabric_sku_id]
    if foam_spec_id is not None:
        matches = [li for li in matches if li.get("foam_spec_id") == foam_spec_id]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
