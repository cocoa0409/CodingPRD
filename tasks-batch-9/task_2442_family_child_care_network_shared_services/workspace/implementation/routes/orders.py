"""PRD 3.8 group purchasing (volume ladder with pinned per-line rounding)."""
from flask import Blueprint

import auth
import calculations as calc
import db
import response
import services
import validators as v
from errors import ApiError

bp = Blueprint("orders", __name__)

CATEGORIES = ("SUPPLIES", "CURRICULUM", "INSURANCE")


def _order(actor, order_id):
    row = services.find_or_404(db.orders, order_id, "ERR_ORDER_NOT_FOUND", "group purchase order")
    auth.scope_provider(actor, row["provider_id"])
    return row


@bp.post("/fccn/group-purchase-orders")
def open_order():
    actor = auth.require_auth(("Provider",))
    body = v.get_body()
    provider_id = v.req_str(body, "provider_id")
    auth.scope_provider(actor, provider_id)
    provider = services.provider_or_404(provider_id)

    category = v.req_enum(body, "category", CATEGORIES)
    raw_lines = v.req_array(body, "lines")
    lines = []
    for item in raw_lines:
        lines.append({
            "sku": v.obj_str(item, "sku", "lines"),
            "unit_price_cents": v.obj_int(item, "unit_price_cents", "lines", 1),
            "quantity": v.obj_int(item, "quantity", "lines", 1),
        })
    v.reject_unversioned(body)

    services.check_posture(provider, restricted_blocks=True)

    row = db.make_row(
        provider_id=provider["id"],
        category=category,
        lines=lines,
        total_quantity=0,
        discount_pct=0,
        subtotal_cents=0,
        insurance_admin_fee_cents=0,
        total_cents=0,
        status="OPEN",
    )
    services.register_new(row)
    db.orders[row["id"]] = row
    return response.created(row)


@bp.post("/fccn/group-purchase-orders/<order_id>/commit")
def commit_order(order_id):
    actor = auth.require_auth(("Provider",))
    order = _order(actor, order_id)
    provider = db.providers[order["provider_id"]]

    if order["status"] != "OPEN":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Only an OPEN order may be committed.")
    if provider["network_posture"] != "OPEN":
        raise ApiError(
            "ERR_PROVIDER_POSTURE_BLOCKED",
            "Group purchasing requires a network posture of OPEN.",
        )

    order.update(calc.group_purchase_total(order))
    order["status"] = "COMMITTED"
    services.touch(order)
    return response.ok(order)


@bp.get("/fccn/group-purchase-orders/<order_id>")
def read_order(order_id):
    actor = auth.require_auth(("NetworkAdmin", "Provider"))
    return response.ok(_order(actor, order_id))
