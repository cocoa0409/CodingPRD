"""RateCard endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    body, serialize, paginate, sort_by_created,
    require_present, as_int, as_str, get_account_or_404, get_rate_card_or_404,
)

bp = Blueprint("rate_cards", __name__)

_NON_NEG_INT_FIELDS = [
    "scheduled_purge_rate_cents_per_kg",
    "onetime_purge_rate_cents_per_kg",
    "onsite_trip_fee_cents",
    "console_swap_fee_cents",
    "storage_rate_cents_per_box_per_period",
    "retrieval_fee_cents",
]


@bp.post("/rate-cards")
def create_rate_card():
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    data = body()
    require_present(data, "account_id", *_NON_NEG_INT_FIELDS)
    account_id = as_str(data["account_id"], "account_id")
    get_account_or_404(account_id)

    card = {"account_id": account_id}
    for f in _NON_NEG_INT_FIELDS:
        val = as_int(data[f], f)
        if val < 0:
            raise err("ERR_INVALID_FIELD_VALUE", "%s must be >= 0" % f)
        card[f] = val

    rush = data.get("rush_retrieval_multiplier_bps", 15000)
    rush = as_int(rush, "rush_retrieval_multiplier_bps")
    if rush < 10000:
        raise err("ERR_INVALID_FIELD_VALUE", "rush_retrieval_multiplier_bps must be >= 10000")
    card["rush_retrieval_multiplier_bps"] = rush
    card["status"] = "DRAFT"

    stamp_create(card)
    db.rate_cards[card["id"]] = card
    return object_response(serialize(card), 201)


@bp.get("/rate-cards/<card_id>")
def get_rate_card(card_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer", "AccountManager"})
    card = get_rate_card_or_404(card_id)
    return object_response(serialize(card), 200)


@bp.get("/rate-cards")
def list_rate_cards():
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer", "AccountManager"})
    items = list(db.rate_cards.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(c) for c in page], limit, offset, total, 200)


@bp.post("/rate-cards/<card_id>/activate")
def activate_rate_card(card_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    card = get_rate_card_or_404(card_id)
    # Supersede the previously ACTIVE card on the same account.
    for c in db.rate_cards.values():
        if (c["account_id"] == card["account_id"]
                and c["status"] == "ACTIVE"
                and c["id"] != card["id"]):
            c["status"] = "SUPERSEDED"
            touch(c)
    card["status"] = "ACTIVE"
    touch(card)
    return object_response(serialize(card), 200)
