"""Team-order routes: create/lines/submit/approve/reject (PRD §3.10, §3.11)."""

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts
from helpers import get_body, parse_pagination, paginate, as_int, as_str
from middleware import require_roles
from response import success, list_success
from routes.common import get_or_404, require_owner
from services import serializers, pricing
from services.inventory import find_row, reserve
from clock import clock

bp = Blueprint("team_orders", __name__)


def _touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] += 1


def _lines_for(team_order_id):
    lines = [l for l in db.team_order_lines.values() if l["team_order_id"] == team_order_id]
    lines.sort(key=lambda l: (l["created_at"], l.get("_seq", 0)))
    return lines


@bp.route("/team-orders", methods=["POST"])
@require_roles("Customer")
def create_team_order():
    body = get_body()
    customer_id = as_str(body, "customer_id", required=True)
    store_id = as_str(body, "store_id", required=True)
    team_name = as_str(body, "team_name", required=True)
    require_owner(customer_id)
    get_or_404(db.customers, customer_id)
    get_or_404(db.stores, store_id)

    ts = now_ts()
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "customer_id": customer_id,
        "store_id": store_id,
        "team_name": team_name,
        "status": "DRAFT",
        "total_units": 0,
        "spawned_order_id": None,
    }
    db.team_orders[rid] = rec
    return success(serializers.team_order(rec), 201)


@bp.route("/team-orders/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "Customer")
def get_team_order(rid):
    rec = get_or_404(db.team_orders, rid)
    return success(serializers.team_order(rec), 200)


@bp.route("/team-orders", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "Customer")
def list_team_orders():
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    store_id = request.args.get("store_id")
    items = list(db.team_orders.values())
    if customer_id is not None:
        items = [t for t in items if t["customer_id"] == customer_id]
    if store_id is not None:
        items = [t for t in items if t["store_id"] == store_id]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.team_order(t) for t in page], limit, offset, total)


@bp.route("/team-orders/<rid>/lines", methods=["POST"])
@require_roles("Customer")
def add_team_order_line(rid):
    team_order = get_or_404(db.team_orders, rid)
    require_owner(team_order["customer_id"])
    body = get_body()
    sku_id = as_str(body, "sku_id", required=True)
    quantity = as_int(body, "quantity", required=True, minimum=1)
    embroidery_text = as_str(body, "embroidery_text", required=False, default=None)
    sku = get_or_404(db.skus, sku_id)

    if team_order["status"] != "DRAFT":
        raise errors.invalid_state("Lines may only be added to a DRAFT team order")

    # Team lines are always embroidered, so the SKU must be embroiderable (§3.10).
    if not sku["embroiderable"]:
        raise errors.ApiError(errors.ERR_EMBROIDERY_NOT_ALLOWED, 422,
                              "Team-order line SKU must be embroiderable")

    # Default embroidery_text to the parent team_name when omitted (§3.10).
    if embroidery_text is None:
        embroidery_text = team_order["team_name"]

    ts = now_ts()
    lid = new_id()
    line = {
        "id": lid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "team_order_id": rid,
        "sku_id": sku_id,
        "quantity": quantity,
        "embroidery_text": embroidery_text,
    }
    db.team_order_lines[lid] = line
    return success(serializers.team_order_line(line), 201)


@bp.route("/team-orders/<rid>/lines", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "Customer")
def list_team_order_lines_for_order(rid):
    get_or_404(db.team_orders, rid)
    limit, offset = parse_pagination()
    items = [l for l in db.team_order_lines.values() if l["team_order_id"] == rid]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.team_order_line(l) for l in page], limit, offset, total)


@bp.route("/team-order-lines", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "Customer")
def list_team_order_lines():
    limit, offset = parse_pagination()
    sku_id = request.args.get("sku_id")
    items = list(db.team_order_lines.values())
    if sku_id is not None:
        items = [l for l in items if l["sku_id"] == sku_id]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.team_order_line(l) for l in page], limit, offset, total)


@bp.route("/team-order-lines/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "Customer")
def get_team_order_line(rid):
    rec = get_or_404(db.team_order_lines, rid)
    return success(serializers.team_order_line(rec), 200)


@bp.route("/team-orders/<rid>/submit", methods=["POST"])
@require_roles("Customer")
def submit_team_order(rid):
    team_order = get_or_404(db.team_orders, rid)
    require_owner(team_order["customer_id"])
    lines = _lines_for(rid)
    # State (priority 6): submit defined from DRAFT with >=1 embroiderable line.
    if team_order["status"] != "DRAFT" or len(lines) == 0:
        raise errors.invalid_state("Team order is not in a submittable state")
    for line in lines:
        sku = db.skus[line["sku_id"]]
        if not sku["embroiderable"]:
            raise errors.ApiError(errors.ERR_EMBROIDERY_NOT_ALLOWED, 422,
                                  "Every team-order line SKU must be embroiderable")
    team_order["total_units"] = sum(l["quantity"] for l in lines)
    team_order["status"] = "SUBMITTED"
    _touch(team_order)
    return success(serializers.team_order(team_order), 200)


@bp.route("/team-orders/<rid>/approve", methods=["POST"])
@require_roles("StoreAssociate")
def approve_team_order(rid):
    team_order = get_or_404(db.team_orders, rid)
    if team_order["status"] != "SUBMITTED":
        raise errors.invalid_state("Team order is not in SUBMITTED state")
    lines = _lines_for(rid)
    clock_dt = clock.now()

    # Inventory availability aggregated per SKU across lines (§3.10), check all
    # before reserving any (atomicity).
    needed = {}
    for line in lines:
        row = find_row(team_order["store_id"], line["sku_id"])
        if row is None:
            raise errors.ApiError(errors.ERR_INSUFFICIENT_INVENTORY, 409,
                                  "No stock row for this store and SKU")
        needed[row["id"]] = needed.get(row["id"], 0) + line["quantity"]
    for row_id, qty in needed.items():
        row = db.store_inventory[row_id]
        if row["available_qty"] < qty:
            raise errors.ApiError(errors.ERR_INSUFFICIENT_INVENTORY, 409,
                                  "Insufficient available inventory for team order")

    customer = db.customers[team_order["customer_id"]]

    # SPAWN cascade: create a child BOPIS order with one line per team line.
    ts = now_ts()
    order_id = new_id()
    spawned = {
        "id": order_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "customer_id": team_order["customer_id"],
        "store_id": team_order["store_id"],
        "fulfillment_type": "BOPIS",
        "payment_status": "AUTHORIZED",
        "fulfillment_status": "RESERVED",
        "provisional_total_cents": 0,
        "final_total_cents": None,
        "loyalty_points_awarded": 0,
    }
    db.orders[order_id] = spawned

    for line in lines:
        row = find_row(team_order["store_id"], line["sku_id"])
        sku = db.skus[line["sku_id"]]
        eff = pricing.effective_unit_price(sku, clock_dt)
        lts = now_ts()
        lid = new_id()
        oline = {
            "id": lid,
            "created_at": lts,
            "updated_at": lts,
            "version": 1,
            "_seq": db.next_seq(),
            "order_id": order_id,
            "sku_id": line["sku_id"],
            "store_inventory_id": row["id"],
            "quantity": line["quantity"],
            "unit_price_cents": eff,
            "embroidery_text": line["embroidery_text"] if line["embroidery_text"] is not None else team_order["team_name"],
            "line_status": "RESERVED",
        }
        db.order_lines[lid] = oline
        reserve(row, line["quantity"])

    # Provisional total with bulk-tier discount (§3.11).
    spawned["provisional_total_cents"] = pricing.team_order_provisional(team_order, customer, clock_dt)

    team_order["spawned_order_id"] = order_id
    team_order["status"] = "APPROVED"
    _touch(team_order)
    return success(serializers.team_order(team_order), 200)


@bp.route("/team-orders/<rid>/reject", methods=["POST"])
@require_roles("StoreAssociate")
def reject_team_order(rid):
    team_order = get_or_404(db.team_orders, rid)
    if team_order["status"] != "SUBMITTED":
        raise errors.invalid_state("Team order is not in SUBMITTED state")
    team_order["status"] = "REJECTED"
    _touch(team_order)
    return success(serializers.team_order(team_order), 200)
