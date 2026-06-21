"""Market + Booth routes (§3.1)."""
from flask import Blueprint

from common import (init_common, touch, require_fields, req_str, req_int,
                    req_date, req_enum, req_bool, paginate)
from db import db
from errors import err
from middleware import get_auth, require_role, get_json_body
from response import success
from routes.helpers import get_or_404, fk_or_404
from serializers import view, view_list
from services import derived

bp = Blueprint("markets", __name__)

SIZE_CLASSES = {"SINGLE", "DOUBLE", "CORNER"}
PRODUCT_CATEGORIES = {"PRODUCE", "DAIRY", "MEAT", "BAKED_GOODS",
                      "PREPARED_FOOD", "CRAFTS", "FLOWERS"}


# ---------------------------------------------------------------------------
# Market
# ---------------------------------------------------------------------------
@bp.route("/markets", methods=["POST"])
def create_market():
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    body = get_json_body()
    require_fields(body, ["name", "season_start_date", "season_end_date",
                          "season_fee_cents", "daily_fee_cents",
                          "commission_bps", "voucher_face_value_cents"])
    name = req_str(body, "name")
    start = req_date(body, "season_start_date")
    end = req_date(body, "season_end_date")
    season_fee = req_int(body, "season_fee_cents")
    daily_fee = req_int(body, "daily_fee_cents")
    commission_bps = req_int(body, "commission_bps")
    face = req_int(body, "voucher_face_value_cents")

    # Bounds (§3.1 -> ERR_VALIDATION_BOUNDS)
    if end < start:
        raise err("ERR_VALIDATION_BOUNDS", "season_end_date < season_start_date")
    if season_fee <= 0 or daily_fee <= 0 or face <= 0:
        raise err("ERR_VALIDATION_BOUNDS", "fee/face-value must be > 0")
    if commission_bps < 0 or commission_bps > 10000:
        raise err("ERR_VALIDATION_BOUNDS", "commission_bps must be 0..10000")

    m = {
        "name": name,
        "season_start_date": start,
        "season_end_date": end,
        "season_fee_cents": season_fee,
        "daily_fee_cents": daily_fee,
        "commission_bps": commission_bps,
        "voucher_face_value_cents": face,
        "booth_count": 0,
        "total_commission_accrued_cents": 0,
        "total_fees_collected_cents": 0,
        "voucher_liability_cents": 0,
    }
    init_common(m)
    db.markets[m["id"]] = m
    return success(view(m), 201)


@bp.route("/markets/<market_id>", methods=["GET"])
def get_market(market_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    m = get_or_404("market", market_id)
    return success(view(m), 200)


# ---------------------------------------------------------------------------
# Booth
# ---------------------------------------------------------------------------
@bp.route("/booths", methods=["POST"])
def create_booth():
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    body = get_json_body()
    require_fields(body, ["market_id", "label", "grid_row", "grid_col", "size_class"])
    market_id = req_str(body, "market_id")
    label = req_str(body, "label")
    grid_row = req_int(body, "grid_row")
    grid_col = req_int(body, "grid_col")
    size_class = req_enum(body, "size_class", SIZE_CLASSES)
    allowed = body.get("allowed_categories", [])
    if not isinstance(allowed, list) or not all(
            isinstance(c, str) and c in PRODUCT_CATEGORIES for c in allowed):
        raise err("ERR_INVALID_REQUEST", "allowed_categories must be an array of product categories")
    if grid_row < 0 or grid_col < 0:
        raise err("ERR_INVALID_REQUEST", "grid_row/grid_col must be >= 0")

    market = fk_or_404("market", market_id)

    # Uniqueness: label per market (ERR_DUPLICATE)
    for b in db.booths.values():
        if b["market_id"] == market_id and b["label"] == label:
            raise err("ERR_DUPLICATE", "Duplicate booth label within market")

    booth = {
        "market_id": market_id,
        "label": label,
        "grid_row": grid_row,
        "grid_col": grid_col,
        "size_class": size_class,
        "allowed_categories": list(allowed),
        "status": "OPEN",
        "season_holder_assignment_id": None,
    }
    init_common(booth)
    db.booths[booth["id"]] = booth
    derived.recompute_booth_count(market)
    return success(view(booth), 201)


@bp.route("/booths/<booth_id>", methods=["GET"])
def get_booth(booth_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    b = get_or_404("booth", booth_id)
    return success(view(b), 200)


@bp.route("/booths", methods=["GET"])
def list_booths():
    from flask import request
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    items = list(db.booths.values())
    market_id = request.args.get("market_id")
    season_holder = request.args.get("season_holder_assignment_id")
    status = request.args.get("status")
    size_class = request.args.get("size_class")
    if market_id is not None:
        items = [b for b in items if b["market_id"] == market_id]
    if season_holder is not None:
        items = [b for b in items if b["season_holder_assignment_id"] == season_holder]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if size_class is not None:
        items = [b for b in items if b["size_class"] == size_class]
    page, meta = paginate(items)
    return success(view_list(page), 200, is_list=True, pagination=meta)


@bp.route("/booths/<booth_id>/set-service", methods=["POST"])
def set_service(booth_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    booth = get_or_404("booth", booth_id)
    body = get_json_body()
    require_fields(body, ["out_of_service"])
    out_of_service = req_bool(body, "out_of_service")
    # Toggle only when not SEASON_HELD (§3.1).
    if booth["status"] == "SEASON_HELD":
        raise err("ERR_INVALID_STATE", "Cannot change service state while SEASON_HELD")
    new_status = "OUT_OF_SERVICE" if out_of_service else "OPEN"
    if booth["status"] != new_status:
        booth["status"] = new_status
        touch(booth)
    return success(view(booth), 200)
