"""IncentivePrize endpoints."""

from flask import Blueprint

import db
import errors
import middleware
from helpers import (
    get_campaign, get_prize, new_id, now_iso,
    req_string, req_int, req_enum, serialize_prize,
)
from middleware import get_body
from response import success_object

bp = Blueprint("prizes", __name__)

TIER_TYPES = ("UNITS_SOLD", "REVENUE_CENTS", "ORDERS_COUNT")


@bp.post("/fundraiser/prizes")
def create_prize():
    middleware.require_role("FundraiserAdmin")
    body = get_body(required=True)
    campaign_id = req_string(body, "campaign_id")
    name = req_string(body, "name")
    tier_type = req_enum(body, "tier_type", TIER_TYPES)
    threshold_value = req_int(body, "threshold_value", minimum=1)
    prize_cost_cents = req_int(body, "prize_cost_cents", minimum=0)
    stock_quantity = req_int(body, "stock_quantity", minimum=0)
    campaign = get_campaign(campaign_id)
    if campaign["status"] not in ("DRAFT", "OPEN"):
        raise errors.err_invalid_state("Prizes may only be created while the campaign is DRAFT or OPEN")
    pid = new_id()
    prize = {
        "id": pid,
        "campaign_id": campaign_id,
        "name": name,
        "tier_type": tier_type,
        "threshold_value": threshold_value,
        "prize_cost_cents": prize_cost_cents,
        "stock_quantity": stock_quantity,
        "remaining_quantity": stock_quantity,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.prizes[pid] = prize
    return success_object(serialize_prize(prize), status=201)


@bp.get("/fundraiser/prizes/<pid>")
def read_prize(pid):
    middleware.any_role()
    prize = get_prize(pid)
    return success_object(serialize_prize(prize))
