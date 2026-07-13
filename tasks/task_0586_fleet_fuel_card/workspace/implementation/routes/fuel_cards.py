"""Fuel cards: issuance, purchase controls, lifecycle (PRD §3.2)."""
from flask import Blueprint, g, request

import response
from db import base_record, db, touch
from errors import err
from middleware import (body, check_fleet, is_fleet_manager, opt_int, paginate, query_enum,
                        req_int, req_num, req_str, require_roles)
from services import serialize
from services.cascade import cancel_card, suspend_card
from services.store import CARD_STATUSES, PRODUCTS, get_account, get_card

bp = Blueprint("fuel_cards", __name__)


def _parse_allowed_products(data):
    products = data.get("allowed_products")
    if not isinstance(products, list) or not products:
        raise err("ERR_VALIDATION", "Field 'allowed_products' is required and must be a non-empty array.")
    for product in products:
        if not isinstance(product, str) or product not in PRODUCTS:
            raise err("ERR_VALIDATION",
                      "Field 'allowed_products' must be a subset of %s." % (list(PRODUCTS),))
    return list(products)


@bp.post("/fuel-cards")
@require_roles("FleetManager")
def issue_card():
    data = body()
    fleet_account_id = req_str(data, "fleet_account_id")
    last4 = req_str(data, "last4")
    allowed_products = _parse_allowed_products(data)
    daily_limit = req_int(data, "daily_dollar_limit_cents", minimum=0)
    gallon_limit = req_num(data, "per_txn_gallon_limit", exclusive_min=0)
    start_hour = opt_int(data, "allowed_start_hour", 0, minimum=0, maximum=23)
    end_hour = opt_int(data, "allowed_end_hour", 24, minimum=1, maximum=24)
    if start_hour >= end_hour:
        raise err("ERR_VALIDATION",
                  "Field 'allowed_start_hour' must be strictly less than 'allowed_end_hour'.")

    account = get_account(fleet_account_id)
    check_fleet(account["id"])

    record = base_record()
    record.update({
        "fleet_account_id": fleet_account_id,
        "last4": last4,
        "status": "ISSUED",
        "allowed_products": allowed_products,
        "daily_dollar_limit_cents": daily_limit,
        "per_txn_gallon_limit": gallon_limit,
        "allowed_start_hour": start_hour,
        "allowed_end_hour": end_hour,
    })
    db.fuel_cards[record["id"]] = record
    return response.created(serialize.fuel_card(record))


@bp.get("/fuel-cards/<card_id>")
@require_roles("FleetManager", "ProgramAdmin")
def fetch_card(card_id):
    card = get_card(card_id)
    check_fleet(card["fleet_account_id"])
    return response.ok(serialize.fuel_card(card))


@bp.get("/fuel-cards")
@require_roles("FleetManager", "ProgramAdmin")
def list_cards():
    account_filter = request.args.get("fleet_account_id")
    status_filter = query_enum("status", CARD_STATUSES)

    if is_fleet_manager():
        if account_filter is not None and account_filter != g.user_id:
            raise err("ERR_FORBIDDEN_FLEET")
        account_filter = g.user_id

    records = list(db.fuel_cards.values())
    if account_filter is not None:
        records = [c for c in records if c["fleet_account_id"] == account_filter]
    if status_filter is not None:
        records = [c for c in records if c["status"] == status_filter]

    page, total, limit, offset = paginate(records)
    return response.listing([serialize.fuel_card(c) for c in page], limit, offset, total)


@bp.post("/fuel-cards/<card_id>/activate")
@require_roles("FleetManager")
def activate(card_id):
    card = get_card(card_id)
    check_fleet(card["fleet_account_id"])
    if card["status"] not in ("ISSUED", "SUSPENDED"):
        raise err("ERR_INVALID_CARD_STATE",
                  "Only an ISSUED or SUSPENDED card can be activated.")
    card["status"] = "ACTIVE"
    touch(card)
    return response.ok(serialize.fuel_card(card))


@bp.post("/fuel-cards/<card_id>/suspend")
@require_roles("FleetManager")
def suspend(card_id):
    card = get_card(card_id)
    check_fleet(card["fleet_account_id"])
    if card["status"] != "ACTIVE":
        raise err("ERR_INVALID_CARD_STATE", "Only an ACTIVE card can be suspended.")
    suspend_card(card)
    return response.ok(serialize.fuel_card(card))


@bp.post("/fuel-cards/<card_id>/cancel")
@require_roles("FleetManager")
def cancel(card_id):
    card = get_card(card_id)
    check_fleet(card["fleet_account_id"])
    if card["status"] == "CANCELLED":
        raise err("ERR_INVALID_CARD_STATE", "Card is already CANCELLED.")
    cancel_card(card)
    return response.ok(serialize.fuel_card(card))
