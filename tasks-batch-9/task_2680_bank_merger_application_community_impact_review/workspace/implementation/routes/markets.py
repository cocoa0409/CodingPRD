"""Deposit market registration and reads (PRD 3.1)."""
from flask import Blueprint

from db import db, new_record, serialize
from errors import ApiError
from helpers import fetch, list_and_respond
from middleware import ALL_ROLES, ROLE_ANALYST, get_body, req_enum, req_str, require_roles
from response import object_response

markets_bp = Blueprint("markets", __name__)

MARKET_TYPES = ("MSA", "RURAL_COUNTY")


@markets_bp.post("/deposit-markets")
@require_roles(ROLE_ANALYST)
def create_market():
    body = get_body(required=True)
    market_code = req_str(body, "market_code", min_len=2, max_len=32)
    market_name = req_str(body, "market_name", min_len=1)
    market_type = req_enum(body, "market_type", MARKET_TYPES)

    for existing in db.markets.values():
        if existing["market_code"] == market_code:
            raise ApiError("ERR_DUPLICATE_MARKET_CODE", "market_code is already registered")

    record = new_record(
        {
            "market_code": market_code,
            "market_name": market_name,
            "market_type": market_type,
            "total_deposits_usd": 0,
            "participant_count": 0,
            "hhi_current": 0,
        }
    )
    db.markets[record["id"]] = record
    return object_response(serialize(record), 201)


@markets_bp.get("/deposit-markets/<record_id>")
@require_roles(*ALL_ROLES)
def get_market(record_id):
    return object_response(serialize(fetch("markets", record_id)))


@markets_bp.get("/deposit-markets")
@require_roles(*ALL_ROLES)
def list_markets():
    return list_and_respond("markets", ("market_type",))
