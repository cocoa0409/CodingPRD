"""Rate cards (PRD 3.3)."""

from flask import Blueprint

from core.auth import authenticate
from core.errors import ApiError
from core.store import db
from core.validate import body, opt_str, req_date, req_int, req_str
from domain.lookup import must, must_ref

from ._common import listing, single

bp = Blueprint("rate_cards", __name__)

READ_ROLES = ("PlatformAdmin", "Dispatcher", "BillingClerk")

PRICE_FIELDS = (
    "price_trim_cents",
    "price_reset_cents",
    "price_new_shoes_cents",
    "price_corrective_cents",
    "price_glue_on_cents",
    "pad_price_cents",
    "trip_fee_zone_a_cents",
    "trip_fee_zone_b_cents",
    "trip_fee_zone_c_cents",
)


@bp.post("/rate-cards")
def create_rate_card():
    authenticate(("PlatformAdmin",))
    data = body()
    must_ref("rate_cards", data.get("supersedes_rate_card_id"))
    label = req_str(data, "label")
    effective_from = req_date(data, "effective_from")
    supersedes = opt_str(data, "supersedes_rate_card_id")
    fields = {name: req_int(data, name) for name in PRICE_FIELDS}
    row = {
        "label": label,
        "effective_from": effective_from,
        "supersedes_rate_card_id": supersedes,
        "status": "DRAFT",
    }
    row.update(fields)
    return single(db.mint("rate_cards", row), 201)


@bp.get("/rate-cards")
def list_rate_cards():
    return listing(
        "rate_cards",
        {"supersedes_rate_card_id": "supersedes_rate_card_id", "status": "status"},
        READ_ROLES,
    )


@bp.get("/rate-cards/<card_id>")
def read_rate_card(card_id):
    authenticate(READ_ROLES)
    return single(must("rate_cards", card_id))


@bp.post("/rate-cards/<card_id>/activate")
def activate_rate_card(card_id):
    authenticate(("PlatformAdmin",))
    card = must("rate_cards", card_id)
    if card["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    predecessor = None
    if card["supersedes_rate_card_id"]:
        predecessor = db.get("rate_cards", card["supersedes_rate_card_id"])
        if predecessor is None or predecessor["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
    card["status"] = "ACTIVE"
    db.touch(card)
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        db.touch(predecessor)
    return single(card)
