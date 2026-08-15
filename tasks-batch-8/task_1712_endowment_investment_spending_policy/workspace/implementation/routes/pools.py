from flask import Blueprint

from constants import ALL_ROLES, INCEPTION_UNIT_PRICE_MILLICENTS
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services.domain import get_or_404, list_response
from util import new_id, parse_body, req_str, req_int

bp = Blueprint("pools", __name__)


@bp.route("/endowment/pools", methods=["POST"])
def create_pool():
    authenticate(["EndowmentAdmin"])
    body = parse_body(required=True)
    pool_name = req_str(body, "pool_name")
    inception_fiscal_year = req_int(body, "inception_fiscal_year", minv=2000, maxv=2100)
    rec = {
        "id": new_id(),
        "pool_name": pool_name,
        "inception_fiscal_year": inception_fiscal_year,
        "pool_status": "ACTIVE",
        "current_quarter_index": 0,
        "current_unit_price_millicents": INCEPTION_UNIT_PRICE_MILLICENTS,
        "total_units_outstanding_micro": 0,
        "total_market_value_cents": 0,
        "version": 1,
    }
    stamp_new(rec)
    store.pools[rec["id"]] = rec
    return success(pub(rec), status=201)


@bp.route("/endowment/pools", methods=["GET"])
def list_pools():
    authenticate(ALL_ROLES)
    return list_response(store.pools, [("pool_status", "pool_status", "str")])


@bp.route("/endowment/pools/<pool_id>", methods=["GET"])
def get_pool(pool_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.pools, pool_id, "EndowmentPool")))


@bp.route("/endowment/pools/<pool_id>/suspend", methods=["POST"])
def suspend_pool(pool_id):
    authenticate(["EndowmentAdmin"])
    pool = get_or_404(store.pools, pool_id, "EndowmentPool")
    if pool["pool_status"] != "ACTIVE":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot suspend a pool in state {pool['pool_status']}",
        )
    pool["pool_status"] = "SUSPENDED"
    bump(pool)
    return success(pub(pool))


@bp.route("/endowment/pools/<pool_id>/resume", methods=["POST"])
def resume_pool(pool_id):
    authenticate(["EndowmentAdmin"])
    pool = get_or_404(store.pools, pool_id, "EndowmentPool")
    if pool["pool_status"] != "SUSPENDED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot resume a pool in state {pool['pool_status']}",
        )
    pool["pool_status"] = "ACTIVE"
    bump(pool)
    return success(pub(pool))


@bp.route("/endowment/pools/<pool_id>/terminate", methods=["POST"])
def terminate_pool(pool_id):
    authenticate(["BoardMember"])
    pool = get_or_404(store.pools, pool_id, "EndowmentPool")
    if pool["pool_status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot terminate a pool in state {pool['pool_status']}",
        )
    non_terminal = [
        f
        for f in store.funds.values()
        if f["pool_id"] == pool["id"] and f["fund_status"] != "TERMINATED"
    ]
    if non_terminal:
        raise_err(
            "ERR_NOT_TERMINABLE",
            "Pool termination requires every fund of the pool to be TERMINATED",
        )
    pool["pool_status"] = "TERMINATED"
    bump(pool)
    return success(pub(pool))
