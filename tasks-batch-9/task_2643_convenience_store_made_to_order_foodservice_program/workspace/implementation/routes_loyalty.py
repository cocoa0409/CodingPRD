"""Promotion rules, loyalty membership, customer-care adjustments and fuel capture."""

from decimal import Decimal

from flask import Blueprint

from apihttp import authenticate, created, get_body, ok, paginate, query_str
from calc import derive_tier, find_loyalty_account, find_promotion_rule
from core import (
    DAYPARTS,
    base_record,
    db,
    gallons_q,
    round_half_up,
    sort_created,
    touch,
)
from errors import ApiError
from serialize import fuel_transaction_out, loyalty_account_out, promotion_rule_out

bp = Blueprint("loyalty", __name__)

PROMOTION_KINDS = ("FUEL_FOOD_COMBO", "DAYPART_BUNDLE")
DISCOUNT_KINDS = ("PCT_PER_LINE", "CENTS_OFF")
TARGET_STATIONS = ("SANDWICH", "BEVERAGE", "HOT_FOOD", "BAKERY", "ALL")


@bp.post("/promotion-rules")
def create_promotion_rule():
    authenticate(("ChainAdmin",))
    body = get_body()
    code = body.string("code", min_len=1)
    kind = body.enum("kind", PROMOTION_KINDS)
    discount_kind = body.enum("discount_kind", DISCOUNT_KINDS)
    max_discount_cents = body.integer("max_discount_cents", minimum=0)
    valid_dayparts = body.enum_array("valid_dayparts", DAYPARTS)
    stacking_rank = body.integer("stacking_rank", minimum=1)
    discount_bp = body.integer(
        "discount_bp", required=(discount_kind == "PCT_PER_LINE"), default=0,
        minimum=0, maximum=10000,
    )
    discount_cents = body.integer(
        "discount_cents", required=(discount_kind == "CENTS_OFF"), default=0, minimum=0
    )
    min_food_subtotal_cents = body.integer(
        "min_food_subtotal_cents", required=False, default=0, minimum=0
    )
    requires_fuel_gallons = body.number(
        "requires_fuel_gallons", required=False, default=Decimal("0"), minimum=0
    )
    target_station = body.enum(
        "target_station", TARGET_STATIONS, required=False, default="ALL"
    )
    for existing in db.promotion_rules.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE")
    rec = base_record()
    rec.update({
        "code": code,
        "kind": kind,
        "discount_kind": discount_kind,
        "discount_bp": discount_bp,
        "discount_cents": discount_cents,
        "max_discount_cents": max_discount_cents,
        "min_food_subtotal_cents": min_food_subtotal_cents,
        "requires_fuel_gallons": gallons_q(requires_fuel_gallons),
        "target_station": target_station,
        "valid_dayparts": valid_dayparts,
        "stacking_rank": stacking_rank,
        "status": "ACTIVE",
    })
    db.promotion_rules[rec["id"]] = rec
    return created(promotion_rule_out(rec))


@bp.post("/promotion-rules/<rule_id>/suspend")
def suspend_promotion_rule(rule_id):
    authenticate(("ChainAdmin",))
    rule = find_promotion_rule(rule_id)
    rule["status"] = "SUSPENDED"
    touch(rule)
    return ok(promotion_rule_out(rule))


@bp.get("/promotion-rules")
def list_promotion_rules():
    authenticate(("ChainAdmin", "StoreManager"))
    rules = list(db.promotion_rules.values())
    status = query_str("status")
    kind = query_str("kind")
    if status is not None:
        rules = [r for r in rules if r["status"] == status]
    if kind is not None:
        rules = [r for r in rules if r["kind"] == kind]
    return paginate(sort_created(rules), promotion_rule_out)


@bp.post("/loyalty-accounts")
def enroll_loyalty_account():
    authenticate(("ChainAdmin", "StoreTerminal"))
    body = get_body()
    member_code = body.string("member_code", min_len=1)
    email = body.string("email", min_len=1)
    for existing in db.loyalty_accounts.values():
        if existing["member_code"] == member_code:
            raise ApiError("ERR_DUPLICATE_CODE")
    rec = base_record()
    rec.update({
        "member_code": member_code,
        "email": email,
        "points_balance": 0,
        "lifetime_points_earned": 0,
        "lifetime_points_redeemed": 0,
        "points_reversed_total": 0,
        "tier": "BASIC",
    })
    db.loyalty_accounts[rec["id"]] = rec
    return created(loyalty_account_out(rec))


@bp.get("/loyalty-accounts/<account_id>")
def read_loyalty_account(account_id):
    authenticate(("ChainAdmin", "StoreManager", "StoreTerminal", "Customer"))
    return ok(loyalty_account_out(find_loyalty_account(account_id)))


@bp.post("/loyalty-accounts/<account_id>/points-adjustments")
def adjust_points(account_id):
    authenticate(("ChainAdmin",))
    body = get_body()
    delta_points = body.integer("delta_points")
    body.string("reason", min_len=1)
    account = find_loyalty_account(account_id)
    if account["points_balance"] + delta_points < 0:
        raise ApiError("ERR_POINTS_BALANCE_NEGATIVE")
    account["points_balance"] += delta_points
    if delta_points >= 0:
        account["lifetime_points_earned"] += delta_points
    else:
        account["lifetime_points_redeemed"] += -delta_points
    account["tier"] = derive_tier(account["lifetime_points_earned"])
    touch(account)
    return ok(loyalty_account_out(account))


@bp.post("/loyalty-accounts/<account_id>/fuel-transactions")
def record_fuel_transaction(account_id):
    authenticate(("ChainAdmin", "StoreTerminal"))
    body = get_body()
    gallons = body.number("gallons", exclusive_minimum=0)
    price_per_gallon_cents = body.integer("price_per_gallon_cents", minimum=1)
    occurred_at = body.datetime("occurred_at")
    account = find_loyalty_account(account_id)
    gallons = gallons_q(gallons)
    rec = base_record(versioned=False)
    rec.update({
        "loyalty_account_id": account["id"],
        "gallons": gallons,
        "price_per_gallon_cents": price_per_gallon_cents,
        "occurred_at": occurred_at,
        "fuel_spend_cents": round_half_up(gallons * Decimal(price_per_gallon_cents)),
    })
    db.fuel_transactions[rec["id"]] = rec
    return created(fuel_transaction_out(rec))


@bp.get("/loyalty-accounts/<account_id>/fuel-transactions")
def list_fuel_transactions(account_id):
    authenticate(("ChainAdmin", "StoreManager", "StoreTerminal", "Customer"))
    account = find_loyalty_account(account_id)
    txns = [
        t for t in db.fuel_transactions.values() if t["loyalty_account_id"] == account["id"]
    ]
    return paginate(sort_created(txns), fuel_transaction_out)
