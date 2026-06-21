"""PurchaseOrder + ReleaseOrder endpoints (PRD §3.3, §3.4)."""
from flask import Blueprint, request, g

import errors
from errors import ApiError
from db import db
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from services.common import (
    init_common, touch, public, get_body, require_fields, require_positive_int,
    invalid, parse_pagination, paginate, resolve, parse_instant,
)

bp = Blueprint("purchase_orders", __name__)

PO_READ_ROLES = ALL_ROLES
RELEASE_READ_ROLES = ("ProcurementAdmin", "Buyer", "Receiver", "Matcher")


def _parse_bool_filter(value):
    if value is None:
        return None
    return str(value).lower() in ("true", "1", "yes")


@bp.route("/procurement/purchase-orders", methods=["POST"])
@require_roles("Buyer")
def create_purchase_order():
    body = get_body()
    require_fields(body, ["vendor_id", "spend_category_id", "po_type"])
    po_type = body["po_type"]
    if po_type not in ("STANDARD", "BLANKET"):
        invalid("po_type must be STANDARD or BLANKET")

    # Existence: vendor, spend_category (path-order: body declaration order).
    vendor = resolve(db.vendors, body["vendor_id"])
    category = resolve(db.spend_categories, body["spend_category_id"])

    requisition_id = body.get("requisition_id")
    source_quote_id = body.get("source_quote_id")
    if requisition_id is not None:
        resolve(db.requisitions, requisition_id)
    if source_quote_id is not None:
        resolve(db.quotes, source_quote_id)

    is_maverick = vendor["id"] != category.get("preferred_vendor_id")

    if po_type == "STANDARD":
        return _create_standard_po(body, vendor, category, is_maverick)
    return _create_blanket_po(body, vendor, category, is_maverick)


def _create_standard_po(body, vendor, category, is_maverick):
    requisition_id = body.get("requisition_id")
    source_quote_id = body.get("source_quote_id")
    if requisition_id is None:
        invalid("STANDARD PO requires requisition_id")
    if source_quote_id is None:
        invalid("STANDARD PO requires source_quote_id")

    requisition = db.requisitions[requisition_id]
    quote = db.quotes[source_quote_id]

    if requisition["status"] != "APPROVED":
        raise ApiError(errors.ERR_REQUISITION_NOT_APPROVED, 409,
                       "Requisition is not APPROVED")
    if quote["status"] != "AWARDED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "source_quote_id must reference an awarded quote")

    qty_by_sku = {}
    for l in requisition["lines"]:
        qty_by_sku[l["sku"]] = qty_by_sku.get(l["sku"], 0) + l["quantity"]

    lines = []
    total = 0
    committed = 0
    for up in quote["unit_prices"]:
        sku = up["sku"]
        qty = qty_by_sku.get(sku, 0)
        unit_price = up["unit_price_cents"]
        lines.append({
            "sku": sku,
            "quantity": qty,
            "unit_price_cents": unit_price,
            "received_total": 0,
        })
        total += qty * unit_price
        committed += qty * unit_price

    rec = {
        "vendor_id": vendor["id"],
        "spend_category_id": category["id"],
        "requisition_id": requisition_id,
        "source_quote_id": source_quote_id,
        "po_type": "STANDARD",
        "lines": lines,
        "total_amount_cents": total,
        "ceiling_amount_cents": None,
        "remaining_amount_cents": None,
        "valid_from": None,
        "valid_to": None,
        "is_maverick": is_maverick,
        "status": "ISSUED",
    }
    init_common(rec)
    db.purchase_orders[rec["id"]] = rec

    # Write committed_total onto the source requisition.
    requisition["committed_total_cents"] = committed
    touch(requisition)

    return object_response(public(rec), status=201)


def _create_blanket_po(body, vendor, category, is_maverick):
    ceiling = body.get("ceiling_amount_cents")
    valid_from_raw = body.get("valid_from")
    valid_to_raw = body.get("valid_to")
    if ceiling is None or valid_from_raw is None or valid_to_raw is None:
        invalid("BLANKET PO requires ceiling_amount_cents, valid_from, valid_to")
    require_positive_int(ceiling, "ceiling_amount_cents")
    valid_from = parse_instant(valid_from_raw, "valid_from")
    valid_to = parse_instant(valid_to_raw, "valid_to")
    if not (valid_to > valid_from):
        invalid("valid_to must be after valid_from")

    # Blanket period overlap: closed interval, same vendor+category, ISSUED.
    for po in db.purchase_orders.values():
        if (po["po_type"] == "BLANKET" and po["status"] == "ISSUED"
                and po["vendor_id"] == vendor["id"]
                and po["spend_category_id"] == category["id"]):
            ex_from = po["_valid_from_dt"]
            ex_to = po["_valid_to_dt"]
            # Closed intervals overlap when from <= ex_to and ex_from <= to.
            if valid_from <= ex_to and ex_from <= valid_to:
                raise ApiError(errors.ERR_BLANKET_PERIOD_OVERLAP, 409,
                               "Blanket validity period overlaps an existing blanket")

    rec = {
        "vendor_id": vendor["id"],
        "spend_category_id": category["id"],
        "requisition_id": None,
        "source_quote_id": None,
        "po_type": "BLANKET",
        "lines": None,
        "total_amount_cents": ceiling,
        "ceiling_amount_cents": ceiling,
        "remaining_amount_cents": ceiling,
        "valid_from": valid_from_raw,
        "valid_to": valid_to_raw,
        "is_maverick": is_maverick,
        "status": "ISSUED",
        "_valid_from_dt": valid_from,
        "_valid_to_dt": valid_to,
    }
    init_common(rec)
    db.purchase_orders[rec["id"]] = rec
    return object_response(public(rec), status=201)


@bp.route("/procurement/purchase-orders/<pid>", methods=["GET"])
@require_roles(*PO_READ_ROLES)
def get_purchase_order(pid):
    rec = resolve(db.purchase_orders, pid)
    return object_response(public(rec))


@bp.route("/procurement/purchase-orders", methods=["GET"])
@require_roles(*PO_READ_ROLES)
def list_purchase_orders():
    limit, offset = parse_pagination(request.args)
    f = request.args
    vendor_id = f.get("vendor_id")
    spend_category_id = f.get("spend_category_id")
    requisition_id = f.get("requisition_id")
    source_quote_id = f.get("source_quote_id")
    po_type = f.get("po_type")
    status = f.get("status")
    is_maverick = _parse_bool_filter(f.get("is_maverick"))
    items = []
    for rec in db.purchase_orders.values():
        if vendor_id is not None and rec["vendor_id"] != vendor_id:
            continue
        if spend_category_id is not None and rec["spend_category_id"] != spend_category_id:
            continue
        if requisition_id is not None and rec["requisition_id"] != requisition_id:
            continue
        if source_quote_id is not None and rec["source_quote_id"] != source_quote_id:
            continue
        if po_type is not None and rec["po_type"] != po_type:
            continue
        if status is not None and rec["status"] != status:
            continue
        if is_maverick is not None and rec["is_maverick"] != is_maverick:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/procurement/purchase-orders/<pid>/close", methods=["POST"])
@require_roles("Buyer")
def close_purchase_order(pid):
    rec = resolve(db.purchase_orders, pid)
    body = get_body()
    force = bool(body.get("force"))
    if rec["status"] != "ISSUED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "PO is not ISSUED")

    if rec["po_type"] == "STANDARD":
        fully_received = all(
            l["received_total"] >= l["quantity"] for l in rec["lines"]
        )
        if not fully_received and not force:
            raise ApiError(errors.ERR_PO_NOT_FULLY_RECEIVED, 409,
                           "PO is not fully received")
    else:  # BLANKET
        has_open = any(
            ro["blanket_po_id"] == rec["id"] and ro["status"] == "OPEN"
            for ro in db.release_orders.values()
        )
        if has_open:
            raise ApiError(errors.ERR_BLANKET_HAS_OPEN_RELEASES, 409,
                           "Blanket has open releases")

    rec["status"] = "CLOSED"
    touch(rec)
    return object_response(public(rec))


@bp.route("/procurement/purchase-orders/<pid>/cancel", methods=["POST"])
@require_roles("Buyer")
def cancel_purchase_order(pid):
    rec = resolve(db.purchase_orders, pid)
    if rec["status"] != "ISSUED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "PO is not ISSUED")

    has_posted_receipt = any(
        gr["purchase_order_id"] == rec["id"] and gr["status"] == "POSTED"
        for gr in db.goods_receipts.values()
    )
    if has_posted_receipt:
        raise ApiError(errors.ERR_PO_HAS_RECEIPTS, 409,
                       "PO has posted goods receipts")

    if rec["po_type"] == "BLANKET":
        for ro in db.release_orders.values():
            if ro["blanket_po_id"] == rec["id"] and ro["status"] == "OPEN":
                ro["status"] = "CANCELLED"
                touch(ro)
                rec["remaining_amount_cents"] += ro["amount_cents"]
                touch(rec)

    rec["status"] = "CANCELLED"
    touch(rec)
    return object_response(public(rec))


# -----------------------------------------------------------------------------
# ReleaseOrder
# -----------------------------------------------------------------------------
def _validate_release_lines(lines, amount_cents):
    if not isinstance(lines, list) or len(lines) == 0:
        invalid("lines must be a non-empty array")
    line_sum = 0
    for l in lines:
        if not isinstance(l, dict):
            invalid("each line must be an object")
        if "sku" not in l or not isinstance(l["sku"], str) or l["sku"] == "":
            invalid("each line requires a sku")
        if "quantity" not in l:
            invalid("each line requires a quantity")
        require_positive_int(l["quantity"], "quantity")
        if "unit_price_cents" not in l:
            invalid("each line requires unit_price_cents")
        require_positive_int(l["unit_price_cents"], "unit_price_cents")
        line_sum += l["quantity"] * l["unit_price_cents"]
    if line_sum != amount_cents:
        invalid("sum of line quantity*unit_price_cents must equal amount_cents")


@bp.route("/procurement/release-orders", methods=["POST"])
@require_roles("Buyer")
def create_release_order():
    body = get_body()
    require_fields(body, ["blanket_po_id", "amount_cents", "lines",
                          "expected_purchase_order_version"])
    blanket = resolve(db.purchase_orders, body["blanket_po_id"])

    amount_cents = body["amount_cents"]
    require_positive_int(amount_cents, "amount_cents")
    _validate_release_lines(body["lines"], amount_cents)

    expected_version = body["expected_purchase_order_version"]

    # priority 7: must reference a BLANKET PO.
    if blanket["po_type"] != "BLANKET":
        raise ApiError(errors.ERR_NOT_BLANKET_PO, 409,
                       "blanket_po_id must reference a BLANKET purchase order")
    # State legality: the blanket must be ISSUED to draw against.
    if blanket["status"] != "ISSUED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Blanket PO is not ISSUED")

    # priority 14: ceiling check.
    if amount_cents > blanket["remaining_amount_cents"]:
        raise ApiError(errors.ERR_RELEASE_EXCEEDS_CEILING, 409,
                       "Release amount exceeds blanket remaining ceiling")

    # priority 15: OCC on the blanket version.
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        invalid("expected_purchase_order_version must be an integer")
    if expected_version != blanket["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_purchase_order_version is stale")

    lines = [
        {"sku": l["sku"], "quantity": l["quantity"],
         "unit_price_cents": l["unit_price_cents"]}
        for l in body["lines"]
    ]
    rec = {
        "blanket_po_id": blanket["id"],
        "amount_cents": amount_cents,
        "lines": lines,
        "status": "OPEN",
    }
    init_common(rec)
    db.release_orders[rec["id"]] = rec

    blanket["remaining_amount_cents"] -= amount_cents
    touch(blanket)

    return object_response(public(rec), status=201)


@bp.route("/procurement/release-orders/<rid>", methods=["GET"])
@require_roles(*RELEASE_READ_ROLES)
def get_release_order(rid):
    rec = resolve(db.release_orders, rid)
    return object_response(public(rec))


@bp.route("/procurement/release-orders", methods=["GET"])
@require_roles(*RELEASE_READ_ROLES)
def list_release_orders():
    limit, offset = parse_pagination(request.args)
    blanket_po_id = request.args.get("blanket_po_id")
    status = request.args.get("status")
    items = []
    for rec in db.release_orders.values():
        if blanket_po_id is not None and rec["blanket_po_id"] != blanket_po_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/procurement/release-orders/<rid>/cancel", methods=["POST"])
@require_roles("Buyer")
def cancel_release_order(rid):
    rec = resolve(db.release_orders, rid)
    if rec["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Release is not OPEN")

    has_posted_receipt = any(
        gr["release_order_id"] == rec["id"] and gr["status"] == "POSTED"
        for gr in db.goods_receipts.values()
    )
    if has_posted_receipt:
        raise ApiError(errors.ERR_RELEASE_HAS_RECEIPTS, 409,
                       "Release has posted goods receipts")

    rec["status"] = "CANCELLED"
    touch(rec)

    blanket = db.purchase_orders.get(rec["blanket_po_id"])
    if blanket is not None:
        blanket["remaining_amount_cents"] += rec["amount_cents"]
        touch(blanket)

    return object_response(public(rec))
