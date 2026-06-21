"""DistributionOrder routes (PRD §3.11). Self-distribution wholesale lifecycle."""
from flask import Blueprint, request

import calculations as calc
from db import db, common_fields, touch
from errors import (
    err, ERR_INVALID_STATE, ERR_WINERY_SUSPENDED, ERR_INSUFFICIENT_INVENTORY,
)
from middleware import authenticate, authorize
from response import success
from serialize import public
from ledger_service import append_ledger
from validate import (
    get_json_body, require_str, require_positive_int, require_enum,
    get_or_404, resolve_winery_fk, resolve_fk,
)
from pagination import paginate, sorted_by_creation

bp = Blueprint("distribution_orders", __name__)


def _new_order(winery_id, product_id, retailer_license_number, dest_state_code,
               case_count, bottles_ordered, wholesale_total):
    o = common_fields()
    o.update({
        "winery_id": winery_id,
        "product_id": product_id,
        "retailer_license_number": retailer_license_number,
        "dest_state_code": dest_state_code,
        "case_count": case_count,
        "bottles_ordered": bottles_ordered,
        "wholesale_total_cents": wholesale_total,
        "status": "DRAFT",
    })
    return o


@bp.route("/distribution-orders", methods=["POST"])
def create_order():
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    body = get_json_body()
    winery_id = require_str(body, "winery_id")
    product_id = require_str(body, "product_id")
    retailer = require_str(body, "retailer_license_number")
    dest_state = require_str(body, "dest_state_code")
    case_count = require_positive_int(body, "case_count")
    with db.lock:
        resolve_winery_fk(winery_id)
        product = resolve_fk(db.products, product_id, winery_id)
        bottles_ordered, wholesale_total = calc.distribution_invoice(
            case_count, product["list_price_cents"]
        )
        o = _new_order(winery_id, product_id, retailer, dest_state, case_count,
                       bottles_ordered, wholesale_total)
        db.distribution_orders[o["id"]] = o
        return success(public(o), status=201)


@bp.route("/distribution-orders", methods=["GET"])
def list_orders():
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    with db.lock:
        items = list(db.distribution_orders.values())
        winery_id = request.args.get("winery_id")
        product_id = request.args.get("product_id")
        status = request.args.get("status")
        dest_state = request.args.get("dest_state_code")
        if winery_id is not None:
            items = [o for o in items if o["winery_id"] == winery_id]
        if product_id is not None:
            items = [o for o in items if o["product_id"] == product_id]
        if status is not None:
            items = [o for o in items if o["status"] == status]
        if dest_state is not None:
            items = [o for o in items if o["dest_state_code"] == dest_state]
        items = sorted_by_creation(items)
        page, pg = paginate(items)
        return success([public(o) for o in page], pagination=pg)


@bp.route("/distribution-orders/<dist_order_id>", methods=["GET"])
def get_order(dist_order_id):
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    with db.lock:
        o = get_or_404(db.distribution_orders, dist_order_id)
        return success(public(o))


@bp.route("/distribution-orders/<dist_order_id>/transitions", methods=["POST"])
def transition_order(dist_order_id):
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    with db.lock:
        o = get_or_404(db.distribution_orders, dist_order_id)
        body = get_json_body()
        action = require_enum(body, "action", {"SUBMIT", "SHIP", "INVOICE", "CANCEL"})
        product = db.products.get(o["product_id"])
        winery = db.wineries.get(o["winery_id"])

        if action == "SUBMIT":
            if o["status"] != "DRAFT":
                raise err(ERR_INVALID_STATE, "Order is not DRAFT")
            if product["status"] != "ACTIVE":
                raise err(ERR_INVALID_STATE, "Product is not ACTIVE")
            if product["free_bottles"] < o["bottles_ordered"]:
                raise err(ERR_INSUFFICIENT_INVENTORY, "Insufficient free inventory")
            o["status"] = "SUBMITTED"
            touch(o)

        elif action == "SHIP":
            if o["status"] != "SUBMITTED":
                raise err(ERR_INVALID_STATE, "Order is not SUBMITTED")
            if winery["status"] != "ACTIVE":
                raise err(ERR_WINERY_SUSPENDED, "Winery is suspended")
            if product["free_bottles"] < o["bottles_ordered"]:
                raise err(ERR_INSUFFICIENT_INVENTORY, "Insufficient free inventory")
            product["on_hand_bottles"] = product["on_hand_bottles"] - o["bottles_ordered"]
            product["free_bottles"] = product["on_hand_bottles"] - product["allocated_bottles"]
            touch(product)
            o["status"] = "SHIPPED"
            touch(o)
            append_ledger(winery["id"], "DISTRIBUTION_REMOVAL", "DISTRIBUTION_ORDER", o["id"],
                          0, 0, f"Distribution removal of {o['bottles_ordered']} bottles")

        elif action == "INVOICE":
            if o["status"] != "SHIPPED":
                raise err(ERR_INVALID_STATE, "Order is not SHIPPED")
            # finalize wholesale_total_cents (recompute to be safe)
            bottles_ordered, wholesale_total = calc.distribution_invoice(
                o["case_count"], product["list_price_cents"]
            )
            o["wholesale_total_cents"] = wholesale_total
            o["status"] = "INVOICED"
            touch(o)

        else:  # CANCEL
            if o["status"] not in ("DRAFT", "SUBMITTED"):
                raise err(ERR_INVALID_STATE, "Order cannot be cancelled from its current state")
            o["status"] = "CANCELLED"
            touch(o)

        return success(public(o))
