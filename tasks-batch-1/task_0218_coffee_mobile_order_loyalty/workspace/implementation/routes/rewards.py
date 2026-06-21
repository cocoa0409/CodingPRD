"""Star ledger entries and reward grants (redeem, birthday, list/get)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import helpers
from db import db, new_id, iso_now, iso_format
from clock import clock
from middleware import authenticate, require_roles, require_owner
from response import success_object, success_array
from services import serializers
from services import projections
from services.mutations import touch, append_star_ledger
from constants import (
    REDEEM_STAR_COST,
    FREE_ITEM_MAX_DISCOUNT_CENTS,
    FREE_ITEM_TTL_DAYS,
    BIRTHDAY_MAX_DISCOUNT_CENTS,
    BIRTHDAY_TTL_DAYS,
)

bp = Blueprint("rewards", __name__)


@bp.route("/star-ledger-entries", methods=["GET"])
def list_star_ledger():
    principal = authenticate()
    require_roles(principal, ["Member", "PlatformAdmin"])
    limit, offset = helpers.parse_pagination()
    member_id = request.args.get("member_id")
    order_id = request.args.get("order_id")
    items = list(db.star_ledger_entries.values())
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    if order_id is not None:
        items = [e for e in items if e["order_id"] == order_id]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = helpers.paginate(items, limit, offset)
    return success_array([serializers.star_ledger_out(e) for e in page], limit, offset, total, 200)


@bp.route("/star-ledger-entries/<star_ledger_entry_id>", methods=["GET"])
def get_star_ledger(star_ledger_entry_id):
    principal = authenticate()
    require_roles(principal, ["Member", "PlatformAdmin"])
    e = db.star_ledger_entries.get(star_ledger_entry_id)
    if e is None:
        raise errors.not_found()
    return success_object(serializers.star_ledger_out(e), 200)


@bp.route("/members/<member_id>/rewards/redeem", methods=["POST"])
def redeem_reward(member_id):
    principal = authenticate()
    require_roles(principal, ["Member"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    require_owner(principal, member_id)

    # Sufficient stars to mint a FREE_ITEM reward
    balance = projections.star_balance(member_id)
    if balance < REDEEM_STAR_COST:
        raise errors.insufficient_stars()

    # append REDEEM ledger entry (negative cost), then mint the reward
    append_star_ledger(member_id, "REDEEM", -REDEEM_STAR_COST, order_id=None)

    now = clock.now()
    expires = now + timedelta(days=FREE_ITEM_TTL_DAYS)
    rnow = iso_now()
    rid = new_id()
    reward = {
        "id": rid,
        "created_at": rnow,
        "updated_at": rnow,
        "version": 1,
        "_seq": db.next_seq(),
        "member_id": member_id,
        "kind": "FREE_ITEM",
        "star_cost": REDEEM_STAR_COST,
        "max_discount_cents": FREE_ITEM_MAX_DISCOUNT_CENTS,
        "expires_at": iso_format(expires),
        "status": "ISSUED",
        "reserved_by_order_id": None,
    }
    db.rewards[rid] = reward
    return success_object(serializers.reward_out(reward), 201)


@bp.route("/members/<member_id>/rewards/birthday", methods=["POST"])
def birthday_reward(member_id):
    principal = authenticate()
    require_roles(principal, ["Member"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    require_owner(principal, member_id)

    now = clock.now()
    current_year = now.year
    current_month = now.month

    # birth month from birth_month_day MM-DD
    bmd = member["birth_month_day"]
    try:
        birth_month = int(bmd.split("-")[0])
    except (ValueError, IndexError):
        raise errors.invalid_request("Invalid birth_month_day on member")

    # Birthday-claim constraints (ERR_BIRTHDAY_ALREADY_CLAIMED):
    #   only during birthday month, at most once per calendar year, and no existing
    #   ISSUED BIRTHDAY reward.
    if birth_month != current_month:
        raise errors.birthday_already_claimed("Not within birthday month")
    if member["last_birthday_reward_year"] == current_year:
        raise errors.birthday_already_claimed("Already claimed this calendar year")
    for r in db.rewards.values():
        if (r["member_id"] == member_id and r["kind"] == "BIRTHDAY"
                and r["status"] == "ISSUED"):
            raise errors.birthday_already_claimed("An ISSUED birthday reward already exists")

    expires = now + timedelta(days=BIRTHDAY_TTL_DAYS)
    rnow = iso_now()
    rid = new_id()
    reward = {
        "id": rid,
        "created_at": rnow,
        "updated_at": rnow,
        "version": 1,
        "_seq": db.next_seq(),
        "member_id": member_id,
        "kind": "BIRTHDAY",
        "star_cost": 0,
        "max_discount_cents": BIRTHDAY_MAX_DISCOUNT_CENTS,
        "expires_at": iso_format(expires),
        "status": "ISSUED",
        "reserved_by_order_id": None,
    }
    db.rewards[rid] = reward
    member["last_birthday_reward_year"] = current_year
    touch(member)
    return success_object(serializers.reward_out(reward), 201)


@bp.route("/rewards", methods=["GET"])
def list_rewards():
    principal = authenticate()
    require_roles(principal, ["Member", "PlatformAdmin"])
    limit, offset = helpers.parse_pagination()
    member_id = request.args.get("member_id")
    reserved_by_order_id = request.args.get("reserved_by_order_id")
    status = request.args.get("status")
    items = list(db.rewards.values())
    if member_id is not None:
        items = [r for r in items if r["member_id"] == member_id]
    if reserved_by_order_id is not None:
        items = [r for r in items if r["reserved_by_order_id"] == reserved_by_order_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = helpers.paginate(items, limit, offset)
    return success_array([serializers.reward_out(r) for r in page], limit, offset, total, 200)


@bp.route("/rewards/<reward_id>", methods=["GET"])
def get_reward(reward_id):
    principal = authenticate()
    require_roles(principal, ["Member", "PlatformAdmin"])
    r = db.rewards.get(reward_id)
    if r is None:
        raise errors.not_found()
    return success_object(serializers.reward_out(r), 200)
