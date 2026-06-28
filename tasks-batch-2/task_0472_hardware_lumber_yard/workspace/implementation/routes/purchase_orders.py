"""PurchaseOrder endpoints — reorder / co-op buying (PRD 3.10)."""
from flask import Blueprint, request

import calc
import db
import errors
import helpers
import serialize
import validate
from auth import authenticate, require_roles
from response import ok, created, ok_list

bp = Blueprint("purchase_orders", __name__)


def _validate_lines(raw_lines):
    """Validate the lines array shape; returns a normalized list of dicts."""
    if not isinstance(raw_lines, list):
        raise errors.invalid_request("lines must be an array")
    out = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise errors.invalid_request("each PO line must be an object")
        product_id = entry.get("product_id")
        qty = entry.get("qty")
        unit_cost = entry.get("unit_cost_cents")
        if not isinstance(product_id, str) or product_id.strip() == "":
            raise errors.invalid_request("PO line product_id must be a non-empty string")
        if not validate.is_number(qty) or qty <= 0:
            raise errors.invalid_request("PO line qty must be > 0")
        if not validate.is_int(unit_cost) or unit_cost < 0:
            raise errors.invalid_request("PO line unit_cost_cents must be an integer >= 0")
        out.append({
            "product_id": product_id,
            "qty": qty,
            "unit_cost_cents": unit_cost,
        })
    return out


@bp.route("/purchase-orders", methods=["POST"])
def create_po():
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    data = validate.body()
    vendor_id = validate.require_str(data, "vendor_id")
    raw_lines = validate.require(data, "lines")
    lines = _validate_lines(raw_lines)
    with db.lock:
        helpers.get_or_404(db.vendors, vendor_id)
        # Existence: every referenced product must exist.
        for l in lines:
            helpers.get_or_404(db.products, l["product_id"])
        rec = db.new_record({
            "vendor_id": vendor_id,
            "lines": lines,
            "gross_cents": 0,
            "coop_rebate_cents": 0,
            "net_cost_cents": 0,
            "status": "DRAFT",
        })
        db.purchase_orders[rec["id"]] = rec
        return created(serialize.purchase_order(rec))


@bp.route("/purchase-orders/<rid>", methods=["GET"])
def get_po(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    with db.lock:
        rec = helpers.get_or_404(db.purchase_orders, rid)
        return ok(serialize.purchase_order(rec))


@bp.route("/purchase-orders", methods=["GET"])
def list_pos():
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    limit, offset = validate.pagination()
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    with db.lock:
        items = list(db.purchase_orders.values())
        if vendor_id is not None:
            items = [p for p in items if p["vendor_id"] == vendor_id]
        if status is not None:
            items = [p for p in items if p["status"] == status]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.purchase_order(p) for p in page], limit, offset, total)


@bp.route("/purchase-orders/<rid>/submit", methods=["POST"])
def submit_po(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    with db.lock:
        po = helpers.get_or_404(db.purchase_orders, rid)
        if po["status"] != "DRAFT":
            raise errors.invalid_state("submit is only defined from DRAFT")
        vendor = db.vendors.get(po["vendor_id"])
        # vendor must be ACTIVE
        if vendor is None or vendor["status"] != "ACTIVE":
            raise errors.ApiError(errors.ERR_VENDOR_INACTIVE, 409, "vendor is inactive")
        # lines non-empty
        if not po["lines"]:
            raise errors.ApiError(errors.ERR_EMPTY_PURCHASE_ORDER, 409, "PO has no lines")
        # every line's product must be supplied by this vendor (same error_id)
        for l in po["lines"]:
            product = db.products.get(l["product_id"])
            if product is None or product["vendor_id"] != po["vendor_id"]:
                raise errors.ApiError(errors.ERR_VENDOR_INACTIVE, 409,
                                      "a PO line product is not supplied by the vendor")
        gross, rebate, net = calc.coop_rebate(po["lines"], vendor["coop_rebate_pct"])
        po["gross_cents"] = gross
        po["coop_rebate_cents"] = rebate
        po["net_cost_cents"] = net
        po["status"] = "SUBMITTED"
        db.touch(po)
        return ok(serialize.purchase_order(po))


@bp.route("/purchase-orders/<rid>/receive", methods=["POST"])
def receive_po(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    with db.lock:
        po = helpers.get_or_404(db.purchase_orders, rid)
        if po["status"] != "SUBMITTED":
            raise errors.invalid_state("receive is only defined from SUBMITTED")
        for l in po["lines"]:
            product = db.products.get(l["product_id"])
            if product is not None:
                product["on_hand"] = product["on_hand"] + l["qty"]
                product["reorder_needed"] = calc.reorder_needed(
                    product["on_hand"], product["reorder_point"])
                db.touch(product)
        po["status"] = "RECEIVED"
        db.touch(po)
        return ok(serialize.purchase_order(po))


@bp.route("/purchase-orders/<rid>/cancel", methods=["POST"])
def cancel_po(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    with db.lock:
        po = helpers.get_or_404(db.purchase_orders, rid)
        if po["status"] not in ("DRAFT", "SUBMITTED"):
            raise errors.invalid_state("only a DRAFT or SUBMITTED PO can be cancelled")
        po["status"] = "CANCELLED"
        db.touch(po)
        return ok(serialize.purchase_order(po))
