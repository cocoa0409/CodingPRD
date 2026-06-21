"""GiftCard, GiftCardTxn, and NoShowRecord routes."""
from flask import Blueprint, request

import db
from errors import err
from helpers import (
    get_json_body, require_fields, require_string, require_int, serialize,
    stamp_create, touch, get_pagination, paginate, sort_by_created,
)
from lookups import (
    get_member, get_gift_card, get_gift_card_txn, get_no_show_record,
    require_gift_card_owner,
)
from middleware import authenticate, require_role
from response import success, list_success
from services import engine

bp = Blueprint("giftcards", __name__)


# ============================ GiftCard ============================
@bp.route("/culinary/gift-cards", methods=["POST"])
def issue_gift_card():
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    body = get_json_body()
    require_fields(body, ["code", "owner_member_id", "initial_value_cents"])
    code = require_string(body, "code")
    owner_id = require_string(body, "owner_member_id")
    initial = require_int(body, "initial_value_cents", minimum=1)
    member = get_member(owner_id)
    if p.role == "Member" and owner_id != p.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member may only issue own gift card")
    for gc in db.gift_cards.values():
        if gc["code"] == code:
            raise err("ERR_INVALID_REQUEST", "Gift card code already exists")
    obj = {
        "code": code,
        "owner_member_id": owner_id,
        "initial_value_cents": initial,
        "balance_cents": initial,
        "status": "ACTIVE",
    }
    stamp_create(obj)
    db.gift_cards[obj["id"]] = obj
    txn = {
        "gift_card_id": obj["id"],
        "booking_id": None,
        "kind": "ISSUE",
        "amount_cents": initial,
    }
    stamp_create(txn, full_audit=False)
    db.gift_card_txns[txn["id"]] = txn
    return success(serialize(obj), status=201)


@bp.route("/culinary/gift-cards/<rid>/reload", methods=["POST"])
def reload_gift_card(rid):
    p = authenticate()
    require_role(p, ["Member"])
    gc = get_gift_card(rid)
    require_gift_card_owner(p, gc)
    body = get_json_body()
    require_fields(body, ["amount_cents", "expected_gift_card_version"])
    amount = require_int(body, "amount_cents")
    expected_version = require_int(body, "expected_gift_card_version")
    # state validity (priority 6): must be DEPLETED
    if gc["status"] != "DEPLETED":
        raise err("ERR_INVALID_STATE", "Gift card not DEPLETED")
    # OCC (priority 7)
    if gc["version"] != expected_version:
        raise err("ERR_STALE_GIFT_CARD_VERSION", "Gift card version is stale")
    # reload amount (priority 25)
    if amount < 1:
        raise err("ERR_INVALID_RELOAD_AMOUNT", "Reload amount must be >= 1")
    txn = {
        "gift_card_id": gc["id"],
        "booking_id": None,
        "kind": "RELOAD",
        "amount_cents": amount,
    }
    stamp_create(txn, full_audit=False)
    db.gift_card_txns[txn["id"]] = txn
    gc["balance_cents"] += amount
    gc["status"] = "ACTIVE"
    touch(gc)
    return success(serialize(gc))


@bp.route("/culinary/gift-cards/<rid>/void", methods=["POST"])
def void_gift_card(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin"])
    gc = get_gift_card(rid)
    if gc["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Gift card not ACTIVE")
    gc["status"] = "VOIDED"
    touch(gc)
    return success(serialize(gc))


@bp.route("/culinary/gift-cards/<rid>", methods=["GET"])
def get_gift_card_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    return success(serialize(get_gift_card(rid)))


@bp.route("/culinary/gift-cards", methods=["GET"])
def list_gift_cards():
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    rows = list(db.gift_cards.values())
    for key in ("owner_member_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.route("/culinary/gift-cards/<rid>/transactions", methods=["GET"])
def list_gift_card_txns(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    get_gift_card(rid)
    rows = [t for t in db.gift_card_txns.values() if t["gift_card_id"] == rid]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


# ============================ GiftCardTxn ============================
@bp.route("/culinary/gift-card-transactions/<rid>", methods=["GET"])
def get_gift_card_txn_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    return success(serialize(get_gift_card_txn(rid)))


@bp.route("/culinary/gift-card-transactions", methods=["GET"])
def list_gift_card_transactions():
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    rows = list(db.gift_card_txns.values())
    for key in ("booking_id", "gift_card_id", "kind"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)


# ============================ NoShowRecord ============================
@bp.route("/culinary/no-show-records/<rid>", methods=["GET"])
def get_no_show_route(rid):
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    return success(serialize(get_no_show_record(rid)))


@bp.route("/culinary/no-show-records", methods=["GET"])
def list_no_show_records():
    p = authenticate()
    require_role(p, ["StudioAdmin", "Member"])
    rows = list(db.no_show_records.values())
    for key in ("member_id", "booking_id", "kind"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    rows = sort_by_created(rows)
    limit, offset = get_pagination()
    page, total = paginate(rows, limit, offset)
    return list_success([serialize(r) for r in page], limit, offset, total)
