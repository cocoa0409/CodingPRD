"""RateCard endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
from db import DB, LOCK
from middleware import require_auth
from services.common import (
    new_record, require_body, req_str, req_int, req_number, get_or_404,
)
from .helpers import get_json_body, list_response, single_response

bp = Blueprint("rate_cards", __name__)


@bp.post("/rental-yard/rate-cards")
def create_rate_card():
    require_auth({"YardManager"})
    body = require_body(get_json_body())
    name = req_str(body, "name", 1, 80)
    daily = req_int(body, "daily_rate_cents", 0)
    weekly = req_int(body, "weekly_rate_cents", 0)
    four_week = req_int(body, "four_week_rate_cents", 0)
    deposit = req_int(body, "deposit_cents", 0)
    waiver = req_int(body, "damage_waiver_daily_cents", 0)
    fuel = req_int(body, "fuel_refill_cents_per_liter", 0)
    cleaning = req_int(body, "cleaning_fee_cents", 0)
    multiplier = req_number(body, "late_fee_multiplier", 1.0)

    with LOCK:
        rec = new_record({
            "name": name,
            "daily_rate_cents": daily,
            "weekly_rate_cents": weekly,
            "four_week_rate_cents": four_week,
            "deposit_cents": deposit,
            "damage_waiver_daily_cents": waiver,
            "fuel_refill_cents_per_liter": fuel,
            "cleaning_fee_cents": cleaning,
            "late_fee_multiplier": multiplier,
            "active": True,
        })
        DB.rate_cards[rec["id"]] = rec
    return single_response(rec, 201)


@bp.get("/rental-yard/rate-cards/<rid>")
def get_rate_card(rid):
    rec = get_or_404(DB.rate_cards, rid)
    return single_response(rec)


@bp.get("/rental-yard/rate-cards")
def list_rate_cards():
    return list_response(DB.rate_cards.values())
