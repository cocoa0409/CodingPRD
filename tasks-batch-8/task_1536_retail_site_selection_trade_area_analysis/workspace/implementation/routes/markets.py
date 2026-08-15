"""Markets and existing stores."""

import re

from flask import Blueprint

from db import db
from errors import invalid_state, already_terminal, invalid_request, ApiError
from middleware import require_roles, ALL_API_ROLES
from response import ok_object
from services import (
    new_record, evaluate_market, sync_market, ser_market, ser_store,
)
from util import (
    get_body, req_str, req_int, req_enum, fk_exists, list_response,
)

bp = Blueprint("markets", __name__)

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
_FORMATS = ("EXPRESS", "STANDARD", "FLAGSHIP")

PIPELINE_SITE_STATUSES = {
    "DRAFT", "SCREENED", "MODELED", "SCORED", "FORECAST_LOCKED",
    "IN_COMMITTEE", "APPROVED", "LOI_ACTIVE", "LEASE_EXECUTED", "BUILD_OUT",
}


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------

@bp.post("/api/markets")
def create_market():
    require_roles("PlatformAdmin")
    body = get_body(required=True)
    name = req_str(body, "name")
    state_code = req_str(body, "state_code")
    if not _STATE_CODE_RE.match(state_code):
        raise invalid_request("state_code must be two uppercase letters A-Z")
    rec = new_record()
    rec.update({
        "name": name,
        "state_code": state_code,
        "population": req_int(body, "population", min_v=1),
        "median_household_income_cents": req_int(
            body, "median_household_income_cents", min_v=0),
        "population_growth_bp": req_int(body, "population_growth_bp"),
        "psychographic_index": req_int(body, "psychographic_index",
                                       min_v=0, max_v=200),
        "base_target_stores": req_int(body, "base_target_stores", min_v=1),
        "annual_capex_budget_cents": req_int(body, "annual_capex_budget_cents",
                                             min_v=1),
        "max_rent_psf_cents": req_int(body, "max_rent_psf_cents", min_v=1),
        "prototype_sales_cents": req_int(body, "prototype_sales_cents", min_v=1),
        "market_status": "SCREENING",
        "raw_score": None,
        "screening_tier": None,
        "target_store_count": None,
        "penetration_index": None,
        "final_score": None,
        "open_store_count": 0,
        "committed_capex_cents": 0,
    })
    db.markets[rec["id"]] = rec
    return ok_object(ser_market(rec), status=201)


@bp.get("/api/markets")
def list_markets():
    require_roles(*ALL_API_ROLES)
    return list_response(db.markets.values(), ser_market)


@bp.get("/api/markets/<mid>")
def get_market(mid):
    require_roles(*ALL_API_ROLES)
    rec = db.markets.get(mid)
    if rec is None:
        from errors import not_found
        raise not_found(f"Market not found: {mid}")
    return ok_object(ser_market(rec))


@bp.post("/api/markets/<mid>/evaluate")
def evaluate_market_route(mid):
    require_roles("PlatformAdmin")
    rec = db.markets.get(mid)
    if rec is None:
        from errors import not_found
        raise not_found(f"Market not found: {mid}")
    if rec["market_status"] == "CLOSED":
        raise already_terminal("Market is CLOSED")
    if rec["market_status"] not in ("SCREENING", "DISQUALIFIED"):
        raise invalid_state(
            f"Market in {rec['market_status']} cannot be evaluated")
    sync_market(rec)  # ensure open_store_count is current for the evaluation
    evaluate_market(rec)
    return ok_object(ser_market(rec))


@bp.post("/api/markets/<mid>/close")
def close_market(mid):
    require_roles("PlatformAdmin")
    rec = db.markets.get(mid)
    if rec is None:
        from errors import not_found
        raise not_found(f"Market not found: {mid}")
    if rec["market_status"] == "CLOSED":
        raise already_terminal("Market is CLOSED")
    if rec["market_status"] != "QUALIFIED":
        raise invalid_state(
            f"Market in {rec['market_status']} cannot be closed")
    for s in db.sites.values():
        if (s["market_id"] == mid
                and s["site_status"] in PIPELINE_SITE_STATUSES):
            raise invalid_state(
                "Market has sites in pipeline states and cannot be closed")
    rec["market_status"] = "CLOSED"
    from services import touch
    touch(rec)
    return ok_object(ser_market(rec))


# ---------------------------------------------------------------------------
# Existing stores
# ---------------------------------------------------------------------------

@bp.post("/api/stores")
def create_store():
    require_roles("PlatformAdmin")
    body = get_body(required=True)
    market = fk_exists(body, "market_id", db.markets)
    store_code = req_str(body, "store_code")
    format_type = req_enum(body, "format_type", _FORMATS)
    annual_sales = req_int(body, "annual_sales_cents", min_v=0)
    for s in db.stores.values():
        if s["market_id"] == market["id"] and s["store_code"] == store_code:
            raise ApiError(
                "ERR_DUPLICATE_STORE_CODE", 409,
                f"store_code {store_code} already exists in this market")
    rec = new_record()
    rec.update({
        "market_id": market["id"],
        "store_code": store_code,
        "format_type": format_type,
        "annual_sales_cents": annual_sales,
        "store_status": "OPERATING",
    })
    db.stores[rec["id"]] = rec
    sync_market(market)  # open_store_count += 1 and saturation bubble-up
    return ok_object(ser_store(rec), status=201)


@bp.get("/api/stores")
def list_stores():
    require_roles(*ALL_API_ROLES)
    return list_response(db.stores.values(), ser_store, filters=["market_id"])


@bp.get("/api/stores/<sid>")
def get_store(sid):
    require_roles(*ALL_API_ROLES)
    rec = db.stores.get(sid)
    if rec is None:
        from errors import not_found
        raise not_found(f"Store not found: {sid}")
    return ok_object(ser_store(rec))


@bp.post("/api/stores/<sid>/close")
def close_store(sid):
    require_roles("PlatformAdmin")
    rec = db.stores.get(sid)
    if rec is None:
        from errors import not_found
        raise not_found(f"Store not found: {sid}")
    if rec["store_status"] == "CLOSED":
        raise already_terminal("Store is CLOSED")
    rec["store_status"] = "CLOSED"
    from services import touch
    touch(rec)
    sync_market(db.markets[rec["market_id"]])  # decrement + de-saturation check
    return ok_object(ser_store(rec))
