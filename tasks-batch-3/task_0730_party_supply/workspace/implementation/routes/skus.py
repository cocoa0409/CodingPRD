from __future__ import annotations
from flask import Blueprint, request

from db import db, stamp_common, bump
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_SKU_VERSION,
    ERR_CLEARANCE_PCT_OUT_OF_RANGE,
)
from middleware import require_roles
from pagination import parse_limit_offset, paginate
from response import created, ok, list_response
from routes._helpers import get_body, require_field, as_int, fetch, clean

bp = Blueprint("skus", __name__)


VALID_CATEGORIES = {
    "BALLOON_LATEX",
    "BALLOON_FOIL",
    "COSTUME",
    "TABLEWARE",
    "DECOR",
    "PRINT_CUSTOM",
    "HELIUM",
    "SEASONAL_HALLOWEEN",
}


@bp.route("/skus", methods=["POST"])
@require_roles("StoreManager")
def create_sku():
    body = get_body()
    sku_code = require_field(body, "sku_code")
    category = require_field(body, "category")
    unit_price_cents = as_int(require_field(body, "unit_price_cents"), "unit_price_cents")

    if not isinstance(sku_code, str) or not sku_code:
        raise_error(ERR_INVALID_REQUEST, "sku_code must be non-empty string")
    if category not in VALID_CATEGORIES:
        raise_error(ERR_INVALID_REQUEST, f"category must be one of {sorted(VALID_CATEGORIES)}")
    if unit_price_cents < 0:
        raise_error(ERR_INVALID_REQUEST, "unit_price_cents must be >= 0")
    for existing in db.skus.values():
        if existing["sku_code"] == sku_code:
            raise_error(ERR_INVALID_REQUEST, f"sku_code '{sku_code}' already exists")

    sku = {
        "sku_code": sku_code,
        "category": category,
        "unit_price_cents": unit_price_cents,
        "theme_tag": body.get("theme_tag"),
        "on_hand_qty": 0,
        "reserved_qty": 0,
        "seasonal_window_start": body.get("seasonal_window_start"),
        "seasonal_window_end": body.get("seasonal_window_end"),
        "is_clearance": False,
        "clearance_pct": 0,
    }
    stamp_common(sku)
    db.skus[sku["id"]] = sku
    return created(clean(sku))


@bp.route("/skus/<id>", methods=["GET"])
@require_roles("StoreManager", "StoreClerk", "Customer")
def get_sku(id):
    return ok(clean(fetch(db.skus, id)))


@bp.route("/skus", methods=["GET"])
@require_roles("StoreManager", "StoreClerk", "Customer")
def list_skus():
    limit, offset = parse_limit_offset()
    theme = request.args.get("theme_tag")
    category = request.args.get("category")
    items = list(db.skus.values())
    if theme is not None:
        items = [s for s in items if s.get("theme_tag") == theme]
    if category is not None:
        items = [s for s in items if s.get("category") == category]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


@bp.route("/skus/<id>/clearance", methods=["POST"])
@require_roles("StoreManager")
def sku_clearance(id):
    sku = fetch(db.skus, id)
    body = get_body()
    # state precedes OCC
    if sku.get("is_clearance"):
        raise_error(ERR_INVALID_STATE, "SKU already on clearance")

    # OCC (priority 7)
    expected = body.get("expected_sku_version")
    if expected is None:
        raise_error(ERR_INVALID_REQUEST, "expected_sku_version required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_error(ERR_INVALID_REQUEST, "expected_sku_version must be integer")
    if sku["version"] != expected:
        raise_error(ERR_STALE_SKU_VERSION, "SKU version has advanced")

    pct = body.get("pct")
    if pct is None:
        raise_error(ERR_INVALID_REQUEST, "pct required")
    try:
        pct_f = float(pct)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "pct must be numeric")
        pct_f = 0.0
    if not (0 < pct_f <= 0.9):
        raise_error(ERR_CLEARANCE_PCT_OUT_OF_RANGE, "pct must be in (0, 0.9]")

    sku["is_clearance"] = True
    sku["clearance_pct"] = pct_f
    bump(sku)
    return ok(clean(sku))


@bp.route("/skus/<id>/unclear", methods=["POST"])
@require_roles("StoreManager")
def sku_unclear(id):
    sku = fetch(db.skus, id)
    if not sku.get("is_clearance"):
        raise_error(ERR_INVALID_STATE, "SKU is not on clearance")
    sku["is_clearance"] = False
    sku["clearance_pct"] = 0
    bump(sku)
    return ok(clean(sku))


@bp.route("/skus/<id>/restock", methods=["POST"])
@require_roles("StoreManager")
def sku_restock(id):
    sku = fetch(db.skus, id)
    body = get_body()
    delta = as_int(require_field(body, "delta"), "delta")
    if delta < 0:
        raise_error(ERR_INVALID_REQUEST, "delta must be >= 0")
    sku["on_hand_qty"] = int(sku["on_hand_qty"]) + delta
    bump(sku)
    return ok(clean(sku))
