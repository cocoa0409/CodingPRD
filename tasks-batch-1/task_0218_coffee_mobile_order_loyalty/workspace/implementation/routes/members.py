"""Member, StoredValueCard, WalletTransaction routes."""
from flask import Blueprint

import errors
import helpers
from db import db, new_id, iso_now
from middleware import authenticate, require_roles, require_owner
from response import success_object, success_array
from services import serializers
from services import projections
from services.mutations import touch, append_wallet_txn

bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def create_member():
    # Anonymous (and any authenticated role) may register. PRD §2.1: the only op
    # an Anonymous caller may perform is registering a new member. Auth headers are
    # still required on every request other than registration; registration itself
    # is the exception, so we do NOT require auth headers here.
    body = helpers.get_json_body()
    helpers.require_fields(body, ["email", "full_name", "birth_month_day"])
    email = helpers.require_str(body["email"], "email")
    full_name = helpers.require_str(body["full_name"], "full_name")
    bmd = helpers.require_str(body["birth_month_day"], "birth_month_day")

    # email must be unique across all members
    for m in db.members.values():
        if m["email"] == email:
            raise errors.invalid_request("email already registered")

    now = iso_now()
    mid = new_id()
    member = {
        "id": mid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "email": email,
        "full_name": full_name,
        "birth_month_day": bmd,
        "last_birthday_reward_year": None,
        "status": "ACTIVE",
    }
    db.members[mid] = member

    # Side effect: auto-create exactly one empty StoredValueCard (balance 0).
    cnow = iso_now()
    cid = new_id()
    card = {
        "id": cid,
        "created_at": cnow,
        "updated_at": cnow,
        "version": 1,
        "_seq": db.next_seq(),
        "member_id": mid,
        "auto_reload_enabled": False,
        "auto_reload_threshold_cents": 1000,
        "auto_reload_amount_cents": 2500,
    }
    db.cards[cid] = card

    return success_object(serializers.member_out(member), 201)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    principal = authenticate()
    require_roles(principal, ["Member", "PlatformAdmin"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    require_owner(principal, member_id)
    return success_object(serializers.member_out(member), 200)


@bp.route("/members/<member_id>/close", methods=["POST"])
def close_member(member_id):
    principal = authenticate()
    require_roles(principal, ["Member", "PlatformAdmin"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    require_owner(principal, member_id)

    # state precondition: status ACTIVE and no in-flight order
    if member["status"] != "ACTIVE":
        raise errors.invalid_state("Member is not ACTIVE")
    in_flight = ("PLACED", "IN_PREP", "READY")
    for o in db.orders.values():
        if o["member_id"] == member_id and o["fulfillment_status"] in in_flight:
            raise errors.invalid_state("Member has in-flight orders")

    member["status"] = "CLOSED"
    touch(member)
    # expire every still-ISSUED reward grant the member holds
    for r in db.rewards.values():
        if r["member_id"] == member_id and r["status"] == "ISSUED":
            r["status"] = "EXPIRED"
            touch(r)

    return success_object(serializers.member_out(member), 200)


@bp.route("/members/<member_id>/card", methods=["GET"])
def get_card(member_id):
    principal = authenticate()
    require_roles(principal, ["Member", "PlatformAdmin"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    require_owner(principal, member_id)
    # array of 0..1 card for the member
    cards = [c for c in db.cards.values() if c["member_id"] == member_id]
    cards.sort(key=lambda c: (c["created_at"], c["_seq"]))
    out = [serializers.card_out(c) for c in cards]
    # This list endpoint returns the member's card(s); not a paginated catalog list,
    # but we still honor pagination params per the global contract.
    limit, offset = helpers.parse_pagination()
    total = len(out)
    page = helpers.paginate(out, limit, offset)
    return success_array(page, limit, offset, total, 200)


@bp.route("/members/<member_id>/card", methods=["PATCH"])
def update_card(member_id):
    principal = authenticate()
    require_roles(principal, ["Member"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    require_owner(principal, member_id)
    card = projections.card_for_member(member_id)
    if card is None:
        raise errors.not_found()

    body = helpers.get_json_body()
    if "auto_reload_enabled" in body and body["auto_reload_enabled"] is not None:
        card["auto_reload_enabled"] = helpers.require_bool(
            body["auto_reload_enabled"], "auto_reload_enabled")
    if "auto_reload_threshold_cents" in body and body["auto_reload_threshold_cents"] is not None:
        card["auto_reload_threshold_cents"] = helpers.require_non_negative_int(
            body["auto_reload_threshold_cents"], "auto_reload_threshold_cents")
    if "auto_reload_amount_cents" in body and body["auto_reload_amount_cents"] is not None:
        amt = helpers.require_int(body["auto_reload_amount_cents"], "auto_reload_amount_cents")
        if amt < 500:
            raise errors.invalid_request("auto_reload_amount_cents must be at least 500")
        card["auto_reload_amount_cents"] = amt

    touch(card)
    return success_object(serializers.card_out(card), 200)


@bp.route("/members/<member_id>/card/reload", methods=["POST"])
def reload_card(member_id):
    principal = authenticate()
    require_roles(principal, ["Member"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    require_owner(principal, member_id)
    card = projections.card_for_member(member_id)
    if card is None:
        raise errors.not_found()

    body = helpers.get_json_body()
    helpers.require_fields(body, ["amount_cents"])
    amount = helpers.require_non_negative_int(body["amount_cents"], "amount_cents")

    txn = append_wallet_txn(card["id"], "RELOAD", amount, order_id=None)
    touch(card)  # balance recomputed (derived) + version increments by one
    return success_object(serializers.wallet_txn_out(txn), 201)


@bp.route("/wallet-transactions", methods=["GET"])
def list_wallet_txns():
    from flask import request
    principal = authenticate()
    require_roles(principal, ["Member", "PlatformAdmin"])
    limit, offset = helpers.parse_pagination()

    card_id = request.args.get("card_id")
    order_id = request.args.get("order_id")
    items = list(db.wallet_transactions.values())
    if card_id is not None:
        items = [t for t in items if t["card_id"] == card_id]
    if order_id is not None:
        items = [t for t in items if t["order_id"] == order_id]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    total = len(items)
    page = helpers.paginate(items, limit, offset)
    return success_array([serializers.wallet_txn_out(t) for t in page], limit, offset, total, 200)


@bp.route("/wallet-transactions/<wallet_transaction_id>", methods=["GET"])
def get_wallet_txn(wallet_transaction_id):
    principal = authenticate()
    require_roles(principal, ["Member", "PlatformAdmin"])
    txn = db.wallet_transactions.get(wallet_transaction_id)
    if txn is None:
        raise errors.not_found()
    return success_object(serializers.wallet_txn_out(txn), 200)
