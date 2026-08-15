"""Couplings: register, read with derived counters, receipts, line listing
(PRD §3.2)."""

from flask import Blueprint

from db import store, new_entity, touch, pub
from middleware import require_roles, body, get_or_404, get_str, get_int, get_num
from response import success, list_response
from services import serialize_coupling

bp = Blueprint("couplings", __name__)


@bp.post("/api/couplings")
def create_coupling():
    require_roles("ShopManager")
    data = body()
    initial = get_int(data, "initial_on_hand_qty", min_val=0)
    coupling = new_entity()
    coupling.update({
        "coupling_sku": get_str(data, "coupling_sku"),
        "size_in": get_num(data, "size_in"),
        "unit_price_cents": get_int(data, "unit_price_cents"),
        "initial_on_hand_qty": initial,
        "on_hand_qty": initial,
    })
    store.couplings[coupling["id"]] = coupling
    return success(serialize_coupling(coupling), status=201)


@bp.get("/api/couplings/<cid>")
def get_coupling(cid):
    require_roles("ShopManager", "CounterSales", "ShopTechnician")
    coupling = get_or_404(store.couplings, cid, "coupling")
    return success(serialize_coupling(coupling), status=200)


@bp.post("/api/couplings/<cid>/receipts")
def receive_stock(cid):
    require_roles("ShopManager")
    coupling = get_or_404(store.couplings, cid, "coupling")
    data = body()
    quantity = get_int(data, "quantity", min_val=1)
    coupling["on_hand_qty"] += quantity
    touch(coupling)
    return success(serialize_coupling(coupling), status=200)


@bp.get("/api/couplings/<cid>/assembly-lines")
def list_coupling_lines(cid):
    require_roles("ShopManager", "CounterSales")
    coupling = get_or_404(store.couplings, cid, "coupling")
    items = [l for l in store.lines.values() if l["coupling_id"] == coupling["id"]]
    return list_response(items)
