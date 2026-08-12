from flask import Blueprint

import db
import response
import serializers
from errors import raise_err
from middleware import require_roles
from routes._common import as_dt, as_int, as_str, body, req_field

bp = Blueprint("campaigns", __name__)


@bp.post("/api/campaigns")
def create_campaign():
    require_roles(["COOP_ADMIN"])
    data = body()
    name = as_str(req_field(data, "name"), "name")
    ws = as_dt(req_field(data, "window_start"), "window_start")
    we = as_dt(req_field(data, "window_end"), "window_end")
    price = as_int(req_field(data, "base_price_cents_per_ton"), "base_price_cents_per_ton")

    c = db.stamp_new({
        "name": name,
        "window_start": ws,
        "window_end": we,
        "base_price_cents_per_ton": price,
        "status": "OPEN",
    })
    db.campaigns[c["id"]] = c

    pool = db.stamp_new({
        "campaign_id": c["id"],
        "status": "OPEN",
        "estimated_pool_value_cents": None,
        "gross_pool_value_cents": None,
        "accrued_provisional_cents": 0,
        "final_price_cents_per_lb": None,
    })
    db.pools[pool["id"]] = pool

    return response.success(serializers.campaign(c), 201)


@bp.get("/api/campaigns/<campaign_id>")
def get_campaign(campaign_id):
    require_roles(["COOP_ADMIN", "STATION_OPERATOR", "QUALITY_TECH", "SCHEDULER", "POOL_ACCOUNTANT", "MEMBER"])
    c = db.campaigns.get(campaign_id)
    if not c:
        raise_err("ERR_NOT_FOUND", "Campaign not found")
    return response.success(serializers.campaign(c), 200)


@bp.post("/api/campaigns/<campaign_id>/close")
def close_campaign(campaign_id):
    require_roles(["COOP_ADMIN"])
    c = db.campaigns.get(campaign_id)
    if not c:
        raise_err("ERR_NOT_FOUND", "Campaign not found")
    if c["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Campaign is not OPEN")
    for b in db.bookings.values():
        if b["campaign_id"] == campaign_id and b["status"] in ("CONFIRMED", "IN_USE"):
            raise_err("ERR_INVALID_STATE", "Campaign has bookings in CONFIRMED or IN_USE")
    # cascade: cancel REQUESTED / WAITLISTED bookings
    for b in db.bookings.values():
        if b["campaign_id"] == campaign_id and b["status"] in ("REQUESTED", "WAITLISTED"):
            b["status"] = "CANCELLED"
            db.touch(b)
    c["status"] = "CLOSED"
    db.touch(c)
    return response.success(serializers.campaign(c), 200)


@bp.get("/api/campaigns/<campaign_id>/pools")
def list_campaign_pools(campaign_id):
    require_roles(["COOP_ADMIN", "POOL_ACCOUNTANT", "MEMBER"])
    c = db.campaigns.get(campaign_id)
    if not c:
        raise_err("ERR_NOT_FOUND", "Campaign not found")
    pools = [p for p in db.pools.values() if p["campaign_id"] == campaign_id]
    pools.sort(key=lambda p: (p["created_at"], p["id"]))
    return response.success_list([serializers.pool(p) for p in pools], len(pools), len(pools), 0, 200)
