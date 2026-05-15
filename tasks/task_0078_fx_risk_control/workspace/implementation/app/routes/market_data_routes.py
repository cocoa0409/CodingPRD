"""Currency pairs and market-data quotes."""
from __future__ import annotations

import re
from decimal import Decimal

from flask import Blueprint

from app.auth import require_auth
from app.clock import clock
from app.errors import make_error
from app.numeric import to_decimal, ZERO
from app.responses import success_object
from app.services import positions as positions_service
from app.services.serializers import currency_pair_dto
from app.services.stop_loss import evaluate_all_armed_for_pair
from app.store import store
from app.validation import get_json_body, require_decimal, require_str


CODE_RE = re.compile(r"^[A-Z]{6}$")

bp = Blueprint("market_data", __name__, url_prefix="/fx-risk")


@bp.route("/currency-pairs", methods=["POST"])
@require_auth(["RiskOfficer"])
def create_currency_pair():
    with store.lock:
        body = get_json_body()
        code = require_str(body, "code")
        base_ccy = require_str(body, "base_ccy")
        quote_ccy = require_str(body, "quote_ccy")
        if not CODE_RE.match(code):
            raise make_error("ERR_INVALID_PAIR_FORMAT")
        if code[:3] != base_ccy or code[3:] != quote_ccy:
            raise make_error("ERR_INVALID_PAIR_FORMAT")
        if code in store.pair_index_by_code:
            raise make_error("ERR_INVALID_PAIR_FORMAT", "Currency pair already exists.")
        mid_rate = require_decimal(body, "mid_rate", gt=ZERO)
        daily_vol = require_decimal(body, "daily_volatility", gte=ZERO)
        meta = store.stamp_common(create=True)
        row = {
            **meta,
            "code": code,
            "base_ccy": base_ccy,
            "quote_ccy": quote_ccy,
            "mid_rate": mid_rate,
            "daily_volatility": daily_vol,
        }
        store.currency_pairs[row["id"]] = row
        store.pair_index_by_code[code] = row["id"]
        return success_object(currency_pair_dto(row), status=201)


@bp.route("/market-data/quote", methods=["POST"])
@require_auth(["RiskOfficer", "MarketDataSystem"])
def push_quote():
    with store.lock:
        body = get_json_body()
        code = require_str(body, "code")
        mid_rate = require_decimal(body, "mid_rate", gt=ZERO)
        pair_id = store.pair_index_by_code.get(code)
        if pair_id is None:
            raise make_error("ERR_NOT_FOUND")
        pair = store.currency_pairs[pair_id]
        pair["mid_rate"] = mid_rate
        pair["updated_at"] = clock.now_iso()
        pair["version"] = pair["version"] + 1

        # Cascade: recompute positions, then limit utilisations, then evaluate stop-losses.
        trading_day = clock.today_iso_date()
        positions_service.recompute_all_positions_for_pair(store, code, trading_day)
        affected_traders = {
            k[0] for k in store.position_index.keys() if k[1] == code
        }
        for trader_id in affected_traders:
            positions_service.recompute_warning_status_for_trader(store, trader_id, trading_day)
        evaluate_all_armed_for_pair(store, code)

        return success_object(currency_pair_dto(pair))
