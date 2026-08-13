"""Reels: receive, read, retire (PRD §3.2, §2.7)."""

from flask import Blueprint

from db import store, new_entity, touch, pub
from errors import ApiError, ERR_INVALID_STATE
from middleware import require_roles, body, get_or_404, get_str, get_int, get_num
from response import success
from services import reel_status_for

bp = Blueprint("reels", __name__)


@bp.post("/api/reels")
def create_reel():
    require_roles("ShopManager")
    data = body()
    initial = get_int(data, "initial_length_mm", min_val=1)
    reel = new_entity()
    reel.update({
        "hose_sku": get_str(data, "hose_sku"),
        "hose_diameter_in": get_num(data, "hose_diameter_in"),
        "working_pressure_psi": get_int(data, "working_pressure_psi"),
        "price_per_meter_cents": get_int(data, "price_per_meter_cents"),
        "initial_length_mm": initial,
        "remaining_length_mm": initial,
        "scrap_length_mm": 0,
        # the fresh reel's status comes from the §2.7 ladder applied to the
        # full received length (>= 20000mm puts it at AVAILABLE)
        "status": reel_status_for(initial),
    })
    store.reels[reel["id"]] = reel
    return success(pub(reel), status=201)


@bp.get("/api/reels/<rid>")
def get_reel(rid):
    require_roles("ShopManager", "CounterSales", "ShopTechnician")
    reel = get_or_404(store.reels, rid, "reel")
    return success(pub(reel), status=200)


@bp.post("/api/reels/<rid>/retire")
def retire_reel(rid):
    require_roles("ShopManager")
    reel = get_or_404(store.reels, rid, "reel")
    if reel["status"] == "RETIRED":
        raise ApiError(ERR_INVALID_STATE, 409, "Reel is already RETIRED")
    reel["status"] = "RETIRED"
    touch(reel)
    return success(pub(reel), status=200)
