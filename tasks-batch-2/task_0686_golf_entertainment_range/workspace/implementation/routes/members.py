"""Member, GameCard, GiftCard routes (PRD §3.2; SCAFFOLD §1.5)."""

from flask import Blueprint, request

from db import db, stamp_common, stamp_immutable, touch
from response import success, list_success, parse_pagination, paginate
from middleware import get_caller, require_roles
from errors import (
    raise_err, ERR_DUPLICATE_EMAIL, ERR_INVALID_REQUEST, ERR_INSUFFICIENT_FUNDS,
)
from services import validate as V
from services.lookup import get_or_404
from services.serialize import member_out, game_card_out, gift_card_out

bp = Blueprint("members", __name__)

ALL_ROLES = {"Guest", "FrontDesk", "RangeManager"}


# ---- Member -----------------------------------------------------------------
@bp.post("/golf/members")
def create_member():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    data = V.body()

    email = V.as_str(V.require(data, "email"), "email")
    full_name = V.as_str(V.require(data, "full_name"), "full_name")
    tier = data.get("tier", "STANDARD")
    tier = V.as_enum(tier, "tier", {"STANDARD", "GOLD", "PLATINUM"})

    for m in db.members.values():
        if m["email"] == email:
            raise_err(ERR_DUPLICATE_EMAIL, "email already registered")

    member = stamp_common({
        "email": email,
        "full_name": full_name,
        "tier": tier,
        "wallet_balance_cents": 0,
        "loyalty_points": 0,
        "pending_loyalty_points": 0,
    })
    db.members[member["id"]] = member
    return success(member_out(member), status=201)


@bp.get("/golf/members/<member_id>")
def get_member(member_id):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    m = get_or_404(db.members, member_id, "member")
    return success(member_out(m))


@bp.post("/golf/members/<member_id>/wallet/topup")
def wallet_topup(member_id):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    m = get_or_404(db.members, member_id, "member")
    data = V.body()
    amount = V.as_int(V.require(data, "amount_cents"), "amount_cents")
    if amount < 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be >= 0")
    m["wallet_balance_cents"] += amount
    touch(m)
    return success(member_out(m))


# ---- GameCard ---------------------------------------------------------------
@bp.post("/golf/game-cards")
def create_game_card():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    data = V.body()
    member_id = V.as_str(V.require(data, "member_id"), "member_id")
    credits_total = V.int_min(V.require(data, "credits_total"), "credits_total", 1)
    get_or_404(db.members, member_id, "member")

    card = stamp_common({
        "member_id": member_id,
        "credits_total": credits_total,
        "credits_remaining": credits_total,
        "status": "ACTIVE",
    })
    db.game_cards[card["id"]] = card
    return success(game_card_out(card), status=201)


@bp.get("/golf/game-cards/<card_id>")
def get_game_card(card_id):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    c = get_or_404(db.game_cards, card_id, "game card")
    return success(game_card_out(c))


@bp.get("/golf/game-cards")
def list_game_cards():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    records = list(db.game_cards.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        records = [c for c in records if c["member_id"] == member_id]
    window, total = paginate(records, limit, offset)
    return list_success([game_card_out(c) for c in window], limit, offset, total)


# ---- GiftCard ---------------------------------------------------------------
@bp.post("/golf/gift-cards")
def create_gift_card():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    data = V.body()
    face = V.int_min(V.require(data, "face_value_cents"), "face_value_cents", 1)
    card = stamp_immutable({
        "face_value_cents": face,
        "remaining_cents": face,
        "redeemed_total_cents": 0,
        "status": "ISSUED",
    })
    db.gift_cards[card["id"]] = card
    return success(gift_card_out(card), status=201)


@bp.get("/golf/gift-cards/<gift_card_id>")
def get_gift_card(gift_card_id):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    g = get_or_404(db.gift_cards, gift_card_id, "gift card")
    return success(gift_card_out(g))


@bp.post("/golf/gift-cards/<gift_card_id>/redeem")
def redeem_gift_card(gift_card_id):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    g = get_or_404(db.gift_cards, gift_card_id, "gift card")
    data = V.body()
    member_id = V.as_str(V.require(data, "member_id"), "member_id")
    amount = V.as_int(V.require(data, "amount_cents"), "amount_cents")
    member = get_or_404(db.members, member_id, "member")

    if amount < 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be >= 0")
    if amount > g["remaining_cents"]:
        raise_err(ERR_INSUFFICIENT_FUNDS, "amount exceeds gift card remaining value")

    g["remaining_cents"] -= amount
    g["redeemed_total_cents"] += amount
    if g["remaining_cents"] == 0:
        g["status"] = "DEPLETED"

    member["wallet_balance_cents"] += amount
    touch(member)

    return success(gift_card_out(g))
