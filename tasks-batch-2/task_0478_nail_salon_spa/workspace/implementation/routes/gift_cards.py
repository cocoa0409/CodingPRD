"""Gift cards across their lifecycle (PRD §3.15)."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, get_str, get_int,
                    parse_pagination, paginate)
from db import db
from errors import (err, ERR_DUPLICATE_RESOURCE, ERR_INVALID_STATE,
                    ERR_GIFT_CARD_OVERDRAW, ERR_STALE_VERSION)
from middleware import authorize
from lookup import get_gift_card, get_client
from response import success_object, success_list
from serialize import gift_card_out

bp = Blueprint("gift_cards", __name__)


@bp.route("/gift-cards", methods=["POST"])
def create_gift_card():
    authorize({"FrontDesk", "SalonManager"})
    body = json_body(optional=False)
    code = get_str(body, "code", required=True)
    initial_balance_cents = get_int(body, "initial_balance_cents", required=True, minimum=1)
    purchaser_client_id = body.get("purchaser_client_id")
    if purchaser_client_id is not None:
        get_client(purchaser_client_id)  # FK existence (PRD §2.6)

    for g in db.gift_cards.values():
        if g["code"] == code:
            raise err(ERR_DUPLICATE_RESOURCE, "Gift-card code already exists")

    rec = make_record({
        "code": code,
        "initial_balance_cents": initial_balance_cents,
        "balance_cents": initial_balance_cents,
        "purchaser_client_id": purchaser_client_id,
        "status": "ACTIVE",
    })
    db.gift_cards[rec["id"]] = rec
    return success_object(gift_card_out(rec), status=201)


@bp.route("/gift-cards", methods=["GET"])
def list_gift_cards():
    authorize({"FrontDesk", "SalonManager"})
    items = list(db.gift_cards.values())
    code = request.args.get("code")
    if code is not None:
        items = [g for g in items if g["code"] == code]
    st = request.args.get("status")
    if st is not None:
        items = [g for g in items if g["status"] == st]
    pcid = request.args.get("purchaser_client_id")
    if pcid is not None:
        items = [g for g in items if g["purchaser_client_id"] == pcid]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([gift_card_out(g) for g in page], limit, offset, total)


@bp.route("/gift-cards/<gid>", methods=["GET"])
def get_one_gift_card(gid):
    user_id, role = authorize({"FrontDesk", "SalonManager", "Client"})
    rec = get_gift_card(gid)
    # Client role: gift cards are readable; ownership is on purchaser_client_id,
    # which is informational only (any client may redeem). The reverse-reach read
    # path (/clients/{id}/gift-cards) enforces ownership; a direct fetch by a
    # Client is scoped to a card they purchased.
    if role == "Client" and rec["purchaser_client_id"] != user_id:
        from errors import ERR_FORBIDDEN
        raise err(ERR_FORBIDDEN, "Client may only read their own gift card")
    return success_object(gift_card_out(rec), status=200)


@bp.route("/gift-cards/<gid>/redeem", methods=["POST"])
def redeem_gift_card(gid):
    authorize({"FrontDesk", "SalonManager"})
    rec = get_gift_card(gid)
    body = json_body(optional=False)
    amount_cents = get_int(body, "amount_cents", required=True, minimum=0)
    expected_version = get_int(body, "expected_gift_card_version", required=True)

    # business fiscal: card ACTIVE and no overdraw (priority 16)
    if rec["status"] != "ACTIVE" or amount_cents > rec["balance_cents"]:
        raise err(ERR_GIFT_CARD_OVERDRAW, "Gift card not ACTIVE or overdraw")

    # OCC (priority 17)
    if expected_version != rec["version"]:
        raise err(ERR_STALE_VERSION, "Stale gift-card version")

    rec["balance_cents"] -= amount_cents
    if rec["balance_cents"] == 0:
        rec["status"] = "DEPLETED"
    touch(rec)
    return success_object(gift_card_out(rec), status=200)


@bp.route("/gift-cards/<gid>/void", methods=["POST"])
def void_gift_card(gid):
    authorize({"SalonManager"})
    rec = get_gift_card(gid)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Only an ACTIVE gift card can be voided")
    rec["balance_cents"] = 0
    rec["status"] = "VOID"
    touch(rec)
    return success_object(gift_card_out(rec), status=200)
