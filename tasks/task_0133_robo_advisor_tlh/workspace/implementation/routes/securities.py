"""Security + pricing + correlation-link endpoints."""
from __future__ import annotations

from flask import Blueprint

from config import ASSET_CLASSES
from db import store
from errors import (
    err_correlation_invalid,
    err_fk_not_found,
    err_invalid_state,
)
from middleware import require_auth
from response import success
from routes._helpers import get_json
from services.engine import (
    reevaluate_blocked_harvest_opportunities,
    refresh_positions_market_values_for_security,
    stamp_create,
    stamp_update,
)
from services.serializers import (
    serialize_correlation_link,
    serialize_security,
)

bp = Blueprint("securities", __name__)


@bp.post("/securities")
@require_auth(["Advisor"])
def create_security():
    body = get_json()
    ticker = body.get("ticker")
    if not isinstance(ticker, str) or not (1 <= len(ticker) <= 10) or not ticker.isupper():
        raise err_invalid_state("ticker must be 1–10 uppercase characters.")
    # Uniqueness on ticker.
    for s in store.securities.values():
        if s["ticker"] == ticker:
            raise err_invalid_state(f"ticker {ticker} already registered.")
    asset_class = body.get("asset_class")
    if asset_class not in ASSET_CLASSES:
        raise err_invalid_state(f"asset_class must be one of {ASSET_CLASSES}.")
    group_id = body.get("substantially_identical_group_id")
    if not isinstance(group_id, str) or not group_id:
        raise err_invalid_state("substantially_identical_group_id is required.")
    is_investable = body.get("is_investable", True)
    if not isinstance(is_investable, bool):
        raise err_invalid_state("is_investable must be a boolean.")
    last_price_cents = body.get("last_price_cents")
    if last_price_cents is None or isinstance(last_price_cents, bool) or not isinstance(last_price_cents, int):
        raise err_invalid_state("last_price_cents must be an integer.")
    if last_price_cents < 0:
        raise err_invalid_state("last_price_cents must be >= 0.")

    with store.lock:
        s = {
            "ticker": ticker,
            "asset_class": asset_class,
            "substantially_identical_group_id": group_id,
            "is_investable": is_investable,
            "last_price_cents": last_price_cents,
        }
        stamp_create(s, common=False)
        store.securities[s["id"]] = s
    return success(serialize_security(s), 201)


@bp.post("/_pricing/set")
@require_auth(["Advisor", "system"])
def set_pricing():
    body = get_json()
    sid = body.get("security_id")
    if not isinstance(sid, str):
        raise err_fk_not_found("security_id is required.")
    sec = store.securities.get(sid)
    if not sec:
        raise err_fk_not_found("Security not found.")
    new_price = body.get("last_price_cents")
    if new_price is None or isinstance(new_price, bool) or not isinstance(new_price, int):
        raise err_invalid_state("last_price_cents must be an integer.")
    if new_price < 0:
        raise err_invalid_state("last_price_cents must be >= 0.")
    with store.lock:
        sec["last_price_cents"] = new_price
        refresh_positions_market_values_for_security(sid)
    return success(serialize_security(sec))


@bp.post("/correlation-links")
@require_auth(["Advisor"])
def create_correlation_link():
    body = get_json()
    a = body.get("security_a_id")
    b = body.get("security_b_id")
    corr = body.get("correlation")
    if not isinstance(a, str) or not isinstance(b, str):
        raise err_fk_not_found("security_a_id and security_b_id are required.")
    if a == b:
        raise err_correlation_invalid("security_a_id and security_b_id must differ.")
    if a not in store.securities or b not in store.securities:
        raise err_fk_not_found("Security not found.")
    if corr is None or isinstance(corr, bool) or not isinstance(corr, (int, float)):
        raise err_correlation_invalid("correlation must be a number.")
    if corr < -1.0 or corr > 1.0:
        raise err_correlation_invalid()
    with store.lock:
        link = {
            "security_a_id": a,
            "security_b_id": b,
            "correlation": float(corr),
        }
        stamp_create(link, common=False)
        store.correlation_links[link["id"]] = link
        reevaluate_blocked_harvest_opportunities()
    return success(serialize_correlation_link(link), 201)
