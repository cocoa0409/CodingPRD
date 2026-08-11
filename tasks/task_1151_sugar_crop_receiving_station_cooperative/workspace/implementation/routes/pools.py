from decimal import Decimal

from flask import Blueprint

import db
import response
import serializers
import services.cascade as cascade
from errors import raise_err
from middleware import require_roles
from routes._common import as_decimal, as_int, body, req_field
from services.calc import D, final_pool_price, q0, total_sugar_lbs_for_campaign

bp = Blueprint("pools", __name__)


@bp.get("/api/pools/<pool_id>")
def get_pool(pool_id):
    require_roles(["COOP_ADMIN", "POOL_ACCOUNTANT", "MEMBER"])
    p = db.pools.get(pool_id)
    if not p:
        raise_err("ERR_NOT_FOUND", "Pool not found")
    return response.success(serializers.pool(p), 200)


@bp.post("/api/pools/<pool_id>/open-accrual")
def open_accrual(pool_id):
    require_roles(["POOL_ACCOUNTANT"])
    data = body()
    est = as_int(req_field(data, "estimated_pool_value_cents"), "estimated_pool_value_cents")
    p = db.pools.get(pool_id)
    if not p:
        raise_err("ERR_NOT_FOUND", "Pool not found")
    if p["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Pool is not OPEN")
    campaign = db.campaigns.get(p["campaign_id"])
    if campaign["status"] != "OPEN":
        raise_err("ERR_CAMPAIGN_NOT_OPEN", "Campaign is not OPEN")
    if est <= 0:
        raise_err("ERR_INVALID_REQUEST", "estimated_pool_value_cents must be > 0")
    p["estimated_pool_value_cents"] = est
    p["status"] = "ACCRUING"
    db.touch(p)
    return response.success(serializers.pool(p), 200)


@bp.post("/api/pools/<pool_id>/close")
def close_pool(pool_id):
    require_roles(["POOL_ACCOUNTANT"])
    data = body()
    gross = as_int(req_field(data, "gross_pool_value_cents"), "gross_pool_value_cents")
    p = db.pools.get(pool_id)
    if not p:
        raise_err("ERR_NOT_FOUND", "Pool not found")
    if p["status"] != "ACCRUING":
        raise_err("ERR_INVALID_STATE", "Pool is not ACCRUING")
    campaign = db.campaigns.get(p["campaign_id"])
    if campaign["status"] != "CLOSED":
        raise_err("ERR_INVALID_STATE", "Campaign is not CLOSED")
    # no ticket of the campaign in CREATED/WEIGHED/REWEIGHING/SAMPLED/ACCEPTED
    for t in db.tickets.values():
        b = db.bookings.get(t["booking_id"])
        if not b or b["campaign_id"] != campaign["id"]:
            continue
        if t["status"] in ("CREATED", "WEIGHED", "REWEIGHING", "SAMPLED", "ACCEPTED"):
            raise_err("ERR_INVALID_STATE", "Campaign has tickets not yet in a terminal receiving state")
    # every pile holding allocations from this campaign's tickets must be EMPTY
    campaign_ticket_ids = set()
    for t in db.tickets.values():
        b = db.bookings.get(t["booking_id"])
        if b and b["campaign_id"] == campaign["id"]:
            campaign_ticket_ids.add(t["id"])
    pile_ids = set()
    for a in db.pile_allocations.values():
        if a["ticket_id"] in campaign_ticket_ids:
            pile_ids.add(a["pile_id"])
    for pid in pile_ids:
        pile = db.piles.get(pid)
        if pile and pile["fill_status"] != "EMPTY":
            raise_err("ERR_INVALID_STATE", "A pile holding campaign allocations is not EMPTY")

    total_sugar = total_sugar_lbs_for_campaign(campaign["id"])
    if total_sugar <= 0:
        raise_err("ERR_POOL_NO_SUGAR", "Total post-loss sugar pounds over CREDITED tickets is zero")

    p["gross_pool_value_cents"] = gross
    p["final_price_cents_per_lb"] = final_pool_price(gross, total_sugar)
    p["status"] = "CLOSED"
    db.touch(p)

    campaign["status"] = "SETTLING"
    db.touch(campaign)
    return response.success(serializers.pool(p), 200)


@bp.post("/api/pools/<pool_id>/installments")
def create_installment(pool_id):
    require_roles(["POOL_ACCOUNTANT"])
    data = body()
    pct = as_decimal(req_field(data, "pct_of_estimated"), "pct_of_estimated")
    expected = as_int(req_field(data, "expected_pool_version"), "expected_pool_version")
    p = db.pools.get(pool_id)
    if not p:
        raise_err("ERR_NOT_FOUND", "Pool not found")
    if p["status"] != "ACCRUING":
        raise_err("ERR_POOL_NOT_ACCRUING", "Pool is not ACCRUING")
    if expected != p["version"]:
        raise_err("ERR_STALE_VERSION", "expected_pool_version does not match current pool version")
    if pct <= 0 or pct > 100:
        raise_err("ERR_INSTALLMENT_PCT_INVALID", "pct_of_estimated must be in (0, 100]")
    target = int(q0(pct / Decimal("100") * Decimal(int(p["estimated_pool_value_cents"]))))
    inst = db.stamp_new({
        "pool_id": pool_id,
        "pct_of_estimated": pct,
        "target_amount_cents": target,
        "distributed_amount_cents": 0,
        "status": "SCHEDULED",
    })
    db.installments[inst["id"]] = inst
    db.touch(p)  # creating an installment increments the pool's version
    return response.success(serializers.installment(inst), 201)


@bp.get("/api/pools/<pool_id>/installments")
def list_installments(pool_id):
    require_roles(["COOP_ADMIN", "POOL_ACCOUNTANT", "MEMBER"])
    p = db.pools.get(pool_id)
    if not p:
        raise_err("ERR_NOT_FOUND", "Pool not found")
    items = [i for i in db.installments.values() if i["pool_id"] == pool_id]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    return response.success_list([serializers.installment(i) for i in items], len(items), len(items), 0, 200)
