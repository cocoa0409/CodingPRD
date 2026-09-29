"""Market endpoints (PRD 3.1)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import ALL_ROLES, PLATFORM_ADMIN, body, endpoint
from response import object_response
from routes.common import filtered, list_page, path_lookup
from services import serialize
from util import as_enum, as_int, as_str, get_required

bp = Blueprint("markets", __name__)

STRATEGIC_POSITIONINGS = ("PRICE_LEADER", "AT_PARITY", "PREMIUM")
DEFAULT_CURRENCY_CODE = "USD"
DEFAULT_INDEX_TOLERANCE_BP = 150


@bp.post("/markets")
@endpoint([PLATFORM_ADMIN])
def create_market(user_id, role):
    payload = body()

    market_code = as_str(get_required(payload, "market_code"), "market_code",
                         min_len=1, max_len=32)
    name = as_str(get_required(payload, "name"), "name", min_len=1)
    positioning_raw = as_str(get_required(payload, "strategic_positioning"),
                             "strategic_positioning", min_len=1)
    target_bp = as_int(get_required(payload, "strategic_index_target_bp"),
                       "strategic_index_target_bp", minimum=5000, maximum=15000)
    currency_code = DEFAULT_CURRENCY_CODE
    if payload.get("currency_code") is not None:
        currency_code = as_str(payload["currency_code"], "currency_code", min_len=1)
    tolerance_bp = DEFAULT_INDEX_TOLERANCE_BP
    if payload.get("index_tolerance_bp") is not None:
        tolerance_bp = as_int(payload["index_tolerance_bp"], "index_tolerance_bp",
                              minimum=0)

    positioning = as_enum(positioning_raw, "strategic_positioning",
                          STRATEGIC_POSITIONINGS)

    for existing in db.markets.values():
        if existing["market_code"] == market_code:
            raise err("ERR_DUPLICATE_RESOURCE",
                      "market_code '%s' is already in use." % market_code)

    record = db.new_record()
    record.update({
        "market_code": market_code,
        "name": name,
        "currency_code": currency_code,
        "strategic_positioning": positioning,
        "strategic_index_target_bp": target_bp,
        "index_tolerance_bp": tolerance_bp,
        "observed_index_bp": None,
        "positioning_gap_bp": None,
        "insufficient_data_report_count": 0,
        "pricing_posture": "OPEN",
    })
    db.markets[record["id"]] = record
    return object_response(serialize.market(record), 201)


@bp.get("/markets/<market_id>")
@endpoint(ALL_ROLES)
def read_market(user_id, role, market_id):
    market = path_lookup("markets", market_id, "ERR_MARKET_NOT_FOUND")
    return object_response(serialize.market(market))


@bp.get("/markets")
@endpoint(ALL_ROLES)
def list_markets(user_id, role):
    rows = filtered(db.ordered(db.markets), request.args,
                    [("strategic_positioning", "strategic_positioning"),
                     ("pricing_posture", "pricing_posture")])
    return list_page(rows, serialize.market)
