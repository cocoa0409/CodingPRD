"""Logical clock, plans, members, attendants, gift-cards, and ledger reads."""
from flask import Blueprint

import errors
import serializers
from clock import clock
from constants import CYCLE_LENGTH_DAYS  # noqa: F401 (kept for symmetry)
from db import db, stamp_create, iso
from helpers import (
    get_json_body,
    require_fields,
    parse_datetime,
    parse_pagination,
    paginate,
)
from middleware import authenticate, require_role
from response import success
from services.ledger import reconcile_gift_card_balance

bp = Blueprint("misc", __name__)


# ----------------------------------------------------------------- clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    principal = authenticate()
    require_role(principal, {"Admin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    new_now = parse_datetime(body["to_iso8601"], "to_iso8601")
    clock.set(new_now)
    return success({"now_utc": iso(clock.now())}, status=200)


# ----------------------------------------------------------------- plans
@bp.route("/plans", methods=["POST"])
def create_plan():
    principal = authenticate()
    require_role(principal, {"Admin"})
    body = get_json_body()
    require_fields(body, ["tier", "monthly_fee_cents", "included_floats_per_cycle",
                          "rollover_cap", "retail_float_cents"])

    tier = body["tier"]
    monthly_fee_cents = body["monthly_fee_cents"]
    included = body["included_floats_per_cycle"]
    rollover_cap = body["rollover_cap"]
    retail = body["retail_float_cents"]
    discount = body.get("member_discount_pct", 0.0)
    active = body.get("active", True)

    for name, val in (("monthly_fee_cents", monthly_fee_cents),
                      ("included_floats_per_cycle", included),
                      ("rollover_cap", rollover_cap),
                      ("retail_float_cents", retail)):
        if not isinstance(val, int) or isinstance(val, bool):
            raise errors.invalid_request(f"{name} must be an integer.")
    if not isinstance(discount, (int, float)) or isinstance(discount, bool):
        raise errors.invalid_request("member_discount_pct must be a number.")
    if not isinstance(active, bool):
        raise errors.invalid_request("active must be a boolean.")

    # Numeric-range checks -> ERR_VALIDATION_RANGE (PRD §2.7 / §3.1)
    if monthly_fee_cents < 0:
        raise errors.validation_range("monthly_fee_cents must be >= 0.")
    if included < 0:
        raise errors.validation_range("included_floats_per_cycle must be >= 0.")
    if rollover_cap < 0:
        raise errors.validation_range("rollover_cap must be >= 0.")
    if not (0.0 <= float(discount) <= 1.0):
        raise errors.validation_range("member_discount_pct must be in [0,1].")
    if retail <= 0:
        raise errors.validation_range("retail_float_cents must be > 0.")

    record = {
        "tier": tier,
        "monthly_fee_cents": monthly_fee_cents,
        "included_floats_per_cycle": included,
        "rollover_cap": rollover_cap,
        "member_discount_pct": discount,
        "retail_float_cents": retail,
        "active": active,
    }
    stamp_create(record)
    db.plans[record["id"]] = record
    return success(serializers.plan_out(record), status=201)


@bp.route("/plans/<pid>", methods=["GET"])
def get_plan(pid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    plan = db.plans.get(pid)
    if plan is None:
        raise errors.not_found("Plan not found.")
    return success(serializers.plan_out(plan), status=200)


@bp.route("/plans", methods=["GET"])
def list_plans():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    records = list(db.plans.values())
    active = _bool_filter("active")
    if active is not None:
        records = [r for r in records if r["active"] == active]
    page, meta = paginate(records, limit, offset)
    return success([serializers.plan_out(r) for r in page], status=200, pagination=meta)


# ----------------------------------------------------------------- members
@bp.route("/members", methods=["POST"])
def create_member():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    body = get_json_body()
    require_fields(body, ["email", "full_name"])
    record = {
        "email": body["email"],
        "full_name": body["full_name"],
        "status": "ACTIVE",
        "orientation_completed": False,
        "waiver_signed_version": 0,
        "no_show_strikes": 0,
    }
    stamp_create(record)
    db.members[record["id"]] = record
    return success(serializers.member_out(record), status=201)


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    member = db.members.get(mid)
    if member is None:
        raise errors.not_found("Member not found.")
    if principal.is_member() and principal.user_id != mid:
        raise errors.forbidden()
    return success(serializers.member_out(member), status=200)


@bp.route("/members", methods=["GET"])
def list_members():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    limit, offset = parse_pagination()
    page, meta = paginate(list(db.members.values()), limit, offset)
    return success([serializers.member_out(r) for r in page], status=200, pagination=meta)


# ----------------------------------------------------------------- attendants
@bp.route("/attendants", methods=["POST"])
def create_attendant():
    principal = authenticate()
    require_role(principal, {"Admin"})
    body = get_json_body()
    require_fields(body, ["full_name"])
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise errors.invalid_request("active must be a boolean.")
    record = {"full_name": body["full_name"], "active": active}
    stamp_create(record)
    db.attendants[record["id"]] = record
    return success(serializers.attendant_out(record), status=201)


@bp.route("/attendants/<aid>", methods=["GET"])
def get_attendant(aid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    att = db.attendants.get(aid)
    if att is None:
        raise errors.not_found("Attendant not found.")
    return success(serializers.attendant_out(att), status=200)


@bp.route("/attendants", methods=["GET"])
def list_attendants():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    limit, offset = parse_pagination()
    page, meta = paginate(list(db.attendants.values()), limit, offset)
    return success([serializers.attendant_out(r) for r in page], status=200, pagination=meta)


# ----------------------------------------------------------------- gift-cards
@bp.route("/gift-cards", methods=["POST"])
def create_gift_card():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    body = get_json_body()
    require_fields(body, ["code", "initial_balance_cents"])
    initial = body["initial_balance_cents"]
    if not isinstance(initial, int) or isinstance(initial, bool):
        raise errors.invalid_request("initial_balance_cents must be an integer.")
    if initial <= 0:
        raise errors.validation_range("initial_balance_cents must be > 0.")
    record = {
        "code": body["code"],
        "initial_balance_cents": initial,
        "remaining_balance_cents": initial,
        "status": "ACTIVE",
    }
    stamp_create(record)
    db.gift_cards[record["id"]] = record
    return success(serializers.gift_card_out(record), status=201)


@bp.route("/gift-cards/<gid>", methods=["GET"])
def get_gift_card(gid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    card = db.gift_cards.get(gid)
    if card is None:
        raise errors.not_found("Gift card not found.")
    return success(serializers.gift_card_out(card), status=200)


@bp.route("/gift-cards", methods=["GET"])
def list_gift_cards():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    limit, offset = parse_pagination()
    from flask import request
    records = list(db.gift_cards.values())
    code = request.args.get("code")
    if code is not None:
        records = [r for r in records if r["code"] == code]
    page, meta = paginate(records, limit, offset)
    return success([serializers.gift_card_out(r) for r in page], status=200, pagination=meta)


@bp.route("/gift-cards/<gid>/void", methods=["POST"])
def void_gift_card(gid):
    principal = authenticate()
    require_role(principal, {"Admin"})
    card = db.gift_cards.get(gid)
    if card is None:
        raise errors.not_found("Gift card not found.")
    from db import touch
    card["status"] = "VOID"
    touch(card)
    return success(serializers.gift_card_out(card), status=200)


# ----------------------------------------------------------------- ledgers (reads)
@bp.route("/credit-ledger/<eid>", methods=["GET"])
def get_credit_entry(eid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    entry = db.credit_ledger.get(eid)
    if entry is None:
        raise errors.not_found("Credit-ledger entry not found.")
    if principal.is_member():
        _assert_membership_owned(principal, entry["membership_id"])
    return success(serializers.credit_ledger_out(entry), status=200)


@bp.route("/credit-ledger", methods=["GET"])
def list_credit_ledger():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    from flask import request
    records = list(db.credit_ledger.values())
    membership_id = request.args.get("membership_id")
    booking_id = request.args.get("booking_id")
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    if booking_id is not None:
        records = [r for r in records if r["booking_id"] == booking_id]
    if principal.is_member():
        records = [r for r in records if _membership_owned(principal, r["membership_id"])]
    page, meta = paginate(records, limit, offset)
    return success([serializers.credit_ledger_out(r) for r in page], status=200, pagination=meta)


@bp.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    payment = db.payments.get(pid)
    if payment is None:
        raise errors.not_found("Payment not found.")
    if principal.is_member():
        _assert_payment_owned(principal, payment)
    return success(serializers.payment_out(payment), status=200)


@bp.route("/payments", methods=["GET"])
def list_payments():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    from flask import request
    records = list(db.payments.values())
    booking_id = request.args.get("booking_id")
    gift_card_id = request.args.get("gift_card_id")
    if booking_id is not None:
        records = [r for r in records if r["booking_id"] == booking_id]
    if gift_card_id is not None:
        records = [r for r in records if r["gift_card_id"] == gift_card_id]
    if principal.is_member():
        records = [r for r in records if _payment_owned(principal, r)]
    page, meta = paginate(records, limit, offset)
    return success([serializers.payment_out(r) for r in page], status=200, pagination=meta)


# ----------------------------------------------------------------- helpers
def _bool_filter(name):
    from flask import request
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw.lower() in ("true", "1", "yes")


def _membership_owned(principal, membership_id):
    if membership_id is None:
        return False
    m = db.memberships.get(membership_id)
    return m is not None and m["member_id"] == principal.user_id


def _assert_membership_owned(principal, membership_id):
    if not _membership_owned(principal, membership_id):
        raise errors.forbidden()


def _payment_owned(principal, payment):
    # Ownership resolves through the booking or (gift) card back to the member.
    booking_id = payment.get("booking_id")
    if booking_id is not None:
        b = db.bookings.get(booking_id)
        if b is not None and b["member_id"] == principal.user_id:
            return True
    return False


def _assert_payment_owned(principal, payment):
    if not _payment_owned(principal, payment):
        raise errors.forbidden()
