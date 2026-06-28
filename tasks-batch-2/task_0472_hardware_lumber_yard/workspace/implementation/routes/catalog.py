"""Vendor and Product endpoints (PRD 3.1)."""
from flask import Blueprint, request

import calc
import db
import errors
import helpers
import serialize
import validate
from auth import authenticate, require_roles
from response import ok, created, ok_list

bp = Blueprint("catalog", __name__)

ALL_OPERATORS = {"InventoryManager", "SalesAssociate", "AccountsManager", "RentalClerk"}


# ----------------------------------------------------------------- Vendors ---

@bp.route("/vendors", methods=["POST"])
def create_vendor():
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    data = validate.body()
    name = validate.require_str(data, "name")
    drop_ship = validate.opt_bool(data, "drop_ship_capable", default=False)
    coop = validate.opt_number(data, "coop_rebate_pct", default=0, minimum=0, maximum=0.25)
    with db.lock:
        rec = db.new_record({
            "name": name,
            "drop_ship_capable": drop_ship,
            "coop_rebate_pct": coop,
            "status": "ACTIVE",
        })
        db.vendors[rec["id"]] = rec
        return created(serialize.vendor(rec))


@bp.route("/vendors/<rid>", methods=["GET"])
def get_vendor(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager", "SalesAssociate", "AccountsManager", "RentalClerk"})
    with db.lock:
        rec = helpers.get_or_404(db.vendors, rid)
        return ok(serialize.vendor(rec))


@bp.route("/vendors/<rid>/deactivate", methods=["POST"])
def deactivate_vendor(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    with db.lock:
        rec = helpers.get_or_404(db.vendors, rid)
        rec["status"] = "INACTIVE"
        db.touch(rec)
        return ok(serialize.vendor(rec))


# ---------------------------------------------------------------- Products ---

@bp.route("/products", methods=["POST"])
def create_product():
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    data = validate.body()
    sku = validate.require_str(data, "sku")
    vendor_id = validate.require_str(data, "vendor_id")
    sell_mode = validate.require_enum(data, "sell_mode", {"EACH", "BY_FOOT"})
    aisle = validate.require_str(data, "aisle")
    bin_ = validate.require_str(data, "bin")
    list_price = validate.opt_int(data, "list_price_cents", default=0, minimum=0)
    ppf = validate.opt_int(data, "price_per_foot_cents", default=0, minimum=0)
    cut_fee = validate.opt_int(data, "cut_fee_cents", default=0, minimum=0)
    reorder_point = validate.require_number(data, "reorder_point", minimum=0)
    reorder_qty = validate.require_number(data, "reorder_qty", exclusive_min=0)

    with db.lock:
        # existence: referenced vendor must exist
        helpers.get_or_404(db.vendors, vendor_id)
        # uniqueness (priority 5)
        for p in db.products.values():
            if p["sku"] == sku:
                raise errors.duplicate("sku already in use")
            if p["aisle"] == aisle and p["bin"] == bin_:
                raise errors.duplicate("(aisle, bin) already in use")
        on_hand = 0
        rec = db.new_record({
            "sku": sku,
            "vendor_id": vendor_id,
            "sell_mode": sell_mode,
            "aisle": aisle,
            "bin": bin_,
            "list_price_cents": list_price,
            "price_per_foot_cents": ppf,
            "cut_fee_cents": cut_fee,
            "on_hand": on_hand,
            "reorder_point": reorder_point,
            "reorder_qty": reorder_qty,
            "reorder_needed": calc.reorder_needed(on_hand, reorder_point),
            "status": "ACTIVE",
        })
        db.products[rec["id"]] = rec
        return created(serialize.product(rec))


@bp.route("/products/<rid>", methods=["GET"])
def get_product(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager", "SalesAssociate", "AccountsManager", "RentalClerk"})
    with db.lock:
        rec = helpers.get_or_404(db.products, rid)
        return ok(serialize.product(rec))


@bp.route("/products", methods=["GET"])
def list_products():
    caller = authenticate()
    require_roles(caller, {"InventoryManager", "SalesAssociate"})
    limit, offset = validate.pagination()
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    reorder_needed = validate.query_bool("reorder_needed")
    with db.lock:
        items = list(db.products.values())
        if vendor_id is not None:
            items = [p for p in items if p["vendor_id"] == vendor_id]
        if status is not None:
            items = [p for p in items if p["status"] == status]
        if reorder_needed is not None:
            items = [p for p in items if p["reorder_needed"] == reorder_needed]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.product(p) for p in page], limit, offset, total)


@bp.route("/products/<rid>/adjust-stock", methods=["POST"])
def adjust_stock(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    data = validate.body()
    with db.lock:
        rec = helpers.get_or_404(db.products, rid)
        delta = validate.require_number(data, "delta")
        new_on_hand = rec["on_hand"] + delta
        if new_on_hand < 0:
            new_on_hand = 0
        rec["on_hand"] = new_on_hand
        rec["reorder_needed"] = calc.reorder_needed(new_on_hand, rec["reorder_point"])
        db.touch(rec)
        return ok(serialize.product(rec))


@bp.route("/products/<rid>/discontinue", methods=["POST"])
def discontinue_product(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    with db.lock:
        rec = helpers.get_or_404(db.products, rid)
        rec["status"] = "DISCONTINUED"
        db.touch(rec)
        return ok(serialize.product(rec))
