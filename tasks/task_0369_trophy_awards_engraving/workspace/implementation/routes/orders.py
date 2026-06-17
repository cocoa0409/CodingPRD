from flask import Blueprint, request
from db import db
from errors import err
from response import ok, ok_list
from middleware import authenticate, require_role
from services import serialize
from services.common import (
    get_json_body, stamp_create, touch, paginate, page_slice,
    require_fields, is_str, is_int,
)
from services import pricing
from services import calc
from services.inventory import recompute_components
from services.orders import (
    get_order_or_404, get_line_or_404, enforce_order_ownership,
    lines_for_order, line_has_approved_proof, allocations_for_line,
)

bp = Blueprint("orders", __name__)

SERVICE_LEVELS = {"STANDARD", "EXPEDITED", "RUSH"}


def _default_order_computed():
    return {
        "promo_code_id": None,
        "reorder_source_order_id": None,
        "production_status": "DRAFT",
        "payment_status": "UNPAID",
        "rush_tier": None,
        "estimate_subtotal_cents": 0,
        "estimate_total_cents": 0,
        "invoice_subtotal_cents": None,
        "invoice_total_cents": None,
        "deposit_due_cents": None,
        "amount_paid_cents": 0,
        "line_count": 0,
        "ready_at": None,
        "fulfilled_at": None,
        "due_date_met": None,
    }


# ---------------------------------------------------------------- create / read

@bp.route("/orders", methods=["POST"])
def create_order():
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    body = get_json_body()
    require_fields(body, ["customer_id", "service_level", "due_date"])
    customer_id = body["customer_id"]
    service_level = body["service_level"]
    due_date = body["due_date"]
    promo_code_id = body.get("promo_code_id")

    if not is_str(customer_id):
        raise err("ERR_INVALID_REQUEST", "customer_id must be a string")
    if service_level not in SERVICE_LEVELS:
        raise err("ERR_INVALID_REQUEST", "invalid service_level")
    if not is_str(due_date):
        raise err("ERR_INVALID_REQUEST", "due_date must be a string")
    try:
        pricing.parse_due(due_date)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "due_date is not a valid date")

    # existence
    if customer_id not in db.customers:
        raise err("ERR_NOT_FOUND", "Customer not found")
    if promo_code_id is not None and promo_code_id not in db.promo_codes:
        raise err("ERR_NOT_FOUND", "Promo code not found")

    # Customers may only create orders for themselves
    if caller.role == "Customer" and caller.user_id != customer_id:
        raise err("ERR_FORBIDDEN", "Customers may only create their own orders")

    rec = _default_order_computed()
    rec["customer_id"] = customer_id
    rec["service_level"] = service_level
    rec["due_date"] = due_date
    rec["promo_code_id"] = promo_code_id
    stamp_create(rec)
    db.orders[rec["id"]] = rec
    return ok(serialize.order(rec), 201)


@bp.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    o = get_order_or_404(order_id)
    enforce_order_ownership(caller, o)
    return ok(serialize.order(o))


@bp.route("/orders", methods=["GET"])
def list_orders():
    caller = authenticate()
    require_role(caller, ("ShopStaff", "ShopManager"))
    items = list(db.orders.values())
    cid = request.args.get("customer_id")
    pid = request.args.get("promo_code_id")
    rsid = request.args.get("reorder_source_order_id")
    if cid is not None:
        items = [o for o in items if o["customer_id"] == cid]
    if pid is not None:
        items = [o for o in items if o["promo_code_id"] == pid]
    if rsid is not None:
        items = [o for o in items if o["reorder_source_order_id"] == rsid]
    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return ok_list([serialize.order(o) for o in page], limit, offset, total)


# ---------------------------------------------------------------- edit header

def _revert_priced_to_draft(order):
    """Any edit to a PRICED order invalidates the estimate (PRD §3.2)."""
    if order["production_status"] == "PRICED":
        order["production_status"] = "DRAFT"
        order["rush_tier"] = None
        order["estimate_subtotal_cents"] = 0
        order["estimate_total_cents"] = 0


@bp.route("/orders/<order_id>", methods=["PUT"])
def edit_order(order_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff"))
    o = get_order_or_404(order_id)
    enforce_order_ownership(caller, o)
    body = get_json_body()

    if o["production_status"] not in ("DRAFT", "PRICED"):
        raise err("ERR_INVALID_STATE", "Order header can only be edited while DRAFT or PRICED")

    if "service_level" in body:
        if body["service_level"] not in SERVICE_LEVELS:
            raise err("ERR_INVALID_REQUEST", "invalid service_level")
    if "due_date" in body:
        if not is_str(body["due_date"]):
            raise err("ERR_INVALID_REQUEST", "due_date must be a string")
        try:
            pricing.parse_due(body["due_date"])
        except Exception:
            raise err("ERR_INVALID_REQUEST", "due_date is not a valid date")
    if "promo_code_id" in body and body["promo_code_id"] is not None:
        if body["promo_code_id"] not in db.promo_codes:
            raise err("ERR_NOT_FOUND", "Promo code not found")

    if "service_level" in body:
        o["service_level"] = body["service_level"]
    if "due_date" in body:
        o["due_date"] = body["due_date"]
    if "promo_code_id" in body:
        o["promo_code_id"] = body["promo_code_id"]

    _revert_priced_to_draft(o)
    touch(o)
    return ok(serialize.order(o))


# ---------------------------------------------------------------- lines

@bp.route("/orders/<order_id>/lines", methods=["POST"])
def add_line(order_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff"))
    o = get_order_or_404(order_id)
    enforce_order_ownership(caller, o)
    body = get_json_body()
    require_fields(body, ["catalog_product_id", "quantity"])
    pid = body["catalog_product_id"]
    qty = body["quantity"]
    engraving_text = body.get("engraving_text", "")
    include_logo = body.get("include_logo", False)

    if not is_str(pid):
        raise err("ERR_INVALID_REQUEST", "catalog_product_id must be a string")
    if not is_int(qty) or qty < 1:
        raise err("ERR_INVALID_REQUEST", "quantity must be an integer >= 1")
    if not is_str(engraving_text):
        raise err("ERR_INVALID_REQUEST", "engraving_text must be a string")
    if not isinstance(include_logo, bool):
        raise err("ERR_INVALID_REQUEST", "include_logo must be a boolean")

    product = db.catalog_products.get(pid)
    if product is None:
        raise err("ERR_NOT_FOUND", "Catalog product not found")

    if o["production_status"] not in ("DRAFT", "PRICED"):
        raise err("ERR_INVALID_STATE", "Lines may only be added to a DRAFT or PRICED order")

    if not product.get("active"):
        raise err("ERR_PRODUCT_INACTIVE", "Cannot add a line for an inactive product")

    line = {
        "order_id": order_id,
        "catalog_product_id": pid,
        "quantity": qty,
        "engraving_text": engraving_text,
        "include_logo": include_logo,
        "line_status": "PENDING",
        "assembled_count": 0,
        "char_count": 0,
        "line_subtotal_cents": 0,
        "volume_tier": None,
        "volume_discount_cents": 0,
    }
    stamp_create(line)
    db.order_lines[line["id"]] = line

    o["line_count"] += 1
    _revert_priced_to_draft(o)
    touch(o)
    return ok(serialize.order_line(line), 201)


@bp.route("/orders/<order_id>/lines", methods=["GET"])
def list_order_lines(order_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    o = get_order_or_404(order_id)
    enforce_order_ownership(caller, o)
    limit, offset = paginate()
    items = lines_for_order(order_id)
    page, total = page_slice(items, limit, offset)
    return ok_list([serialize.order_line(l) for l in page], limit, offset, total)


@bp.route("/order-lines/<line_id>", methods=["GET"])
def get_order_line(line_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    line = get_line_or_404(line_id)
    o = db.orders.get(line["order_id"])
    if o is not None:
        enforce_order_ownership(caller, o)
    return ok(serialize.order_line(line))


@bp.route("/order-lines", methods=["GET"])
def list_lines():
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    items = list(db.order_lines.values())
    oid = request.args.get("order_id")
    pid = request.args.get("catalog_product_id")
    if oid is not None:
        items = [l for l in items if l["order_id"] == oid]
    if pid is not None:
        items = [l for l in items if l["catalog_product_id"] == pid]
    # Customer ownership: restrict to lines on owned orders
    if caller.role == "Customer":
        items = [l for l in items
                 if db.orders.get(l["order_id"], {}).get("customer_id") == caller.user_id]
    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return ok_list([serialize.order_line(l) for l in page], limit, offset, total)


@bp.route("/order-lines/<line_id>", methods=["DELETE"])
def delete_line(line_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff"))
    line = get_line_or_404(line_id)
    o = db.orders.get(line["order_id"])
    if o is not None:
        enforce_order_ownership(caller, o)
    if o["production_status"] not in ("DRAFT", "PRICED"):
        raise err("ERR_INVALID_STATE", "Lines may only be removed from a DRAFT or PRICED order")

    del db.order_lines[line_id]
    o["line_count"] -= 1
    _revert_priced_to_draft(o)
    touch(o)
    return ok(serialize.order_line(line))


# ---------------------------------------------------------------- price

@bp.route("/orders/<order_id>/price", methods=["POST"])
def price_order(order_id):
    caller = authenticate()
    require_role(caller, ("ShopStaff",))
    o = get_order_or_404(order_id)

    if o["production_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Order must be DRAFT to price")
    if o["line_count"] < 1:
        raise err("ERR_INVALID_STATE", "Order must have at least one line to price")

    policy, n_active = pricing.active_rush_policy()
    if n_active != 1 or policy is None:
        raise err("ERR_INVALID_STATE", "Exactly one active rush policy is required to price")

    lines = pricing.recompute_lines(o)
    # rush tier (may raise ERR_DUE_DATE_INFEASIBLE)
    rush_tier, surcharge_pct = pricing.resolve_tier_for_order(o, lines, policy)

    subtotal = pricing.order_subtotal(lines)
    promo = db.promo_codes.get(o["promo_code_id"]) if o["promo_code_id"] else None
    pre_promo, _total = calc.order_pricing(subtotal, surcharge_pct, promo, apply_promo=False)

    o["rush_tier"] = rush_tier
    o["estimate_subtotal_cents"] = subtotal
    o["estimate_total_cents"] = pre_promo
    o["production_status"] = "PRICED"
    touch(o)
    return ok(serialize.order(o))


# ---------------------------------------------------------------- confirm (OCC)

@bp.route("/orders/<order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    caller = authenticate()
    require_role(caller, ("Customer",))
    o = get_order_or_404(order_id)
    enforce_order_ownership(caller, o)
    body = get_json_body()
    require_fields(body, ["expected_order_version"])
    expected = body["expected_order_version"]
    if not is_int(expected):
        raise err("ERR_INVALID_REQUEST", "expected_order_version must be an integer")

    # state before OCC (PRD §2.7: ERR_INVALID_STATE precedes business rules; OCC
    # leads the business-rule tier)
    if o["production_status"] != "PRICED":
        raise err("ERR_INVALID_STATE", "Order must be PRICED to confirm")

    # OCC
    if expected != o["version"]:
        raise err("ERR_STALE_VERSION", "Order version is stale")

    lines = lines_for_order(order_id)

    # every line must have an APPROVED proof
    for line in lines:
        if not line_has_approved_proof(line["id"]):
            raise err("ERR_PROOF_NOT_APPROVED", "Every line must have an approved proof")

    # promo validity
    promo = db.promo_codes.get(o["promo_code_id"]) if o["promo_code_id"] else None
    # recompute pricing for invoice & promo-min checks
    pricing.recompute_lines(o)
    lines = lines_for_order(order_id)
    subtotal = pricing.order_subtotal(lines)

    if promo is not None:
        if not promo.get("active"):
            raise err("ERR_PROMO_INVALID", "Promo code is inactive")
        if promo.get("max_uses") is not None and promo["uses_count"] >= promo["max_uses"]:
            raise err("ERR_PROMO_INVALID", "Promo code has reached its maximum uses")
        if subtotal < promo.get("min_subtotal_cents", 0):
            raise err("ERR_PROMO_MIN_NOT_MET", "Order subtotal does not meet promo minimum")

    # component availability: aggregate required qty per component across all lines
    required = {}  # component_id -> total qty
    for line in lines:
        product = db.catalog_products[line["catalog_product_id"]]
        for entry in product.get("bom", []):
            cid = entry["component_id"]
            need = entry["qty_per_unit"] * line["quantity"]
            required[cid] = required.get(cid, 0) + need
    for cid, need in required.items():
        comp = db.components.get(cid)
        if comp is None or comp["available_qty"] < need:
            raise err("ERR_COMPONENT_SHORTAGE", "Insufficient component stock to reserve")

    # ----- all checks passed: commit -----
    policy, _n = pricing.active_rush_policy()
    surcharge_pct = 0
    if policy is not None and o["rush_tier"] is not None:
        surcharge_pct = {
            "RUSH": policy["rush_surcharge_pct"],
            "EXPEDITED": policy["expedited_surcharge_pct"],
            "STANDARD": policy["standard_surcharge_pct"],
        }.get(o["rush_tier"], 0)
    pre_promo, total = calc.order_pricing(subtotal, surcharge_pct, promo, apply_promo=True)
    o["invoice_subtotal_cents"] = subtotal
    o["invoice_total_cents"] = total
    o["deposit_due_cents"] = calc.deposit_due(total, o["rush_tier"])

    # create allocations (one per (line, bom component)), RESERVED
    affected = []
    for line in lines:
        product = db.catalog_products[line["catalog_product_id"]]
        for entry in product.get("bom", []):
            alloc = {
                "order_line_id": line["id"],
                "component_id": entry["component_id"],
                "qty": entry["qty_per_unit"] * line["quantity"],
                "alloc_status": "RESERVED",
            }
            stamp_create(alloc)
            db.component_allocations[alloc["id"]] = alloc
            affected.append(entry["component_id"])
    recompute_components(affected)

    if promo is not None:
        promo["uses_count"] += 1

    o["production_status"] = "CONFIRMED"
    touch(o)
    return ok(serialize.order(o))


# ---------------------------------------------------------------- reorder (OCC)

@bp.route("/orders/<order_id>/reorder", methods=["POST"])
def reorder(order_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff"))
    source = get_order_or_404(order_id)
    enforce_order_ownership(caller, source)
    body = get_json_body()
    require_fields(body, ["expected_order_version"])
    expected = body["expected_order_version"]
    if not is_int(expected):
        raise err("ERR_INVALID_REQUEST", "expected_order_version must be an integer")

    new_due = body.get("due_date", source["due_date"])
    new_service = body.get("service_level", source["service_level"])
    if "due_date" in body:
        if not is_str(new_due):
            raise err("ERR_INVALID_REQUEST", "due_date must be a string")
        try:
            pricing.parse_due(new_due)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "due_date is not a valid date")
    if "service_level" in body and new_service not in SERVICE_LEVELS:
        raise err("ERR_INVALID_REQUEST", "invalid service_level")

    # OCC on source
    if expected != source["version"]:
        raise err("ERR_STALE_VERSION", "Source order version is stale")

    # clone
    new_order = _default_order_computed()
    new_order["customer_id"] = source["customer_id"]
    new_order["service_level"] = new_service
    new_order["due_date"] = new_due
    new_order["promo_code_id"] = source["promo_code_id"]
    new_order["reorder_source_order_id"] = source["id"]
    stamp_create(new_order)
    db.orders[new_order["id"]] = new_order

    src_lines = lines_for_order(source["id"])
    count = 0
    for sl in src_lines:
        line = {
            "order_id": new_order["id"],
            "catalog_product_id": sl["catalog_product_id"],
            "quantity": sl["quantity"],
            "engraving_text": sl.get("engraving_text", ""),
            "include_logo": sl.get("include_logo", False),
            "line_status": "PENDING",
            "assembled_count": 0,
            "char_count": 0,
            "line_subtotal_cents": 0,
            "volume_tier": None,
            "volume_discount_cents": 0,
        }
        stamp_create(line)
        db.order_lines[line["id"]] = line
        count += 1
    new_order["line_count"] = count

    # source version increments
    touch(source)
    return ok(serialize.order(new_order), 201)


# ---------------------------------------------------------------- start-production

@bp.route("/orders/<order_id>/start-production", methods=["POST"])
def start_production(order_id):
    caller = authenticate()
    require_role(caller, ("ShopStaff",))
    o = get_order_or_404(order_id)
    if o["production_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Order must be CONFIRMED to start production")
    if o["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise err("ERR_DEPOSIT_REQUIRED", "Deposit must be collected before production")

    for line in lines_for_order(order_id):
        if line["line_status"] == "PENDING":
            line["line_status"] = "ALLOCATED"
            touch(line)
    o["production_status"] = "IN_PRODUCTION"
    touch(o)
    return ok(serialize.order(o))


# ---------------------------------------------------------------- cancel

@bp.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    caller = authenticate()
    require_role(caller, ("ShopManager",))
    o = get_order_or_404(order_id)
    if o["production_status"] not in ("DRAFT", "PRICED", "CONFIRMED", "IN_PRODUCTION"):
        raise err("ERR_INVALID_STATE", "Only non-terminal orders may be cancelled")

    redeemed = o["production_status"] in ("CONFIRMED", "IN_PRODUCTION")

    # release reserved allocations
    affected = []
    for line in lines_for_order(order_id):
        for alloc in allocations_for_line(line["id"]):
            if alloc["alloc_status"] == "RESERVED":
                alloc["alloc_status"] = "RELEASED"
                touch(alloc)
                affected.append(alloc["component_id"])
    recompute_components(affected)

    # un-redeem promo
    if redeemed and o["promo_code_id"]:
        promo = db.promo_codes.get(o["promo_code_id"])
        if promo is not None and promo["uses_count"] > 0:
            promo["uses_count"] -= 1

    # refund payments
    if o["amount_paid_cents"] > 0:
        for pay in db.payments.values():
            if pay["order_id"] == order_id and pay["pay_status"] == "CAPTURED":
                pay["pay_status"] = "REFUNDED"
        o["payment_status"] = "REFUNDED"
        o["amount_paid_cents"] = 0

    o["production_status"] = "CANCELLED"
    touch(o)
    return ok(serialize.order(o))
