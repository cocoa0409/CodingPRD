"""Shared helpers: response envelope, auth, validation, pagination, calculations,
serializers."""
import json
import random
import string
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import request, jsonify

import store
from errors import err

VALID_ROLES = {"Anonymous", "Member", "Guide", "StoreStaff", "CoopAdmin"}

# ==========================================================================
# Response envelope
# ==========================================================================


def _meta(pagination=None):
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    m = {"api_request_id": rid, "api_request_timestamp": store.now_ts()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, pagination=None, is_array=False):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status


# ==========================================================================
# Auth
# ==========================================================================


class Ctx:
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id


def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed authentication headers")
    return Ctx(role, uid)


def authorize(ctx, allowed_roles):
    if ctx.role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role %s not permitted for this operation" % ctx.role)


def require_owner_member(ctx, member_id):
    """Entity-backed Member may only act on/read its own resources."""
    if ctx.role == "Member" and ctx.user_id != member_id:
        raise err("ERR_UNAUTHORIZED", "Member may only access its own resources")


def require_owner_guide(ctx, guide_id):
    if ctx.role == "Guide" and ctx.user_id != guide_id:
        raise err("ERR_UNAUTHORIZED", "Guide may only access its own resources")


# ==========================================================================
# Body parsing & validation
# ==========================================================================


def get_body():
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", "Missing or invalid field: %s" % field)
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", "Missing or invalid integer field: %s" % field)
    return v


def opt_int(body, field, default=0):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", "Invalid integer field: %s" % field)
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", "Missing or invalid numeric field: %s" % field)
    return v


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise err("ERR_VALIDATION", "Invalid enum value for %s: %s" % (field, v))
    return v


def opt_enum(body, field, allowed, default):
    if field not in body or body.get(field) is None:
        return default
    return require_enum(body, field, allowed)


# ==========================================================================
# Existence lookups
# ==========================================================================

_NOT_FOUND = {
    "members": "ERR_MEMBER_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "rental_units": "ERR_RENTAL_UNIT_NOT_FOUND",
    "reservations": "ERR_RESERVATION_NOT_FOUND",
    "trips": "ERR_TRIP_NOT_FOUND",
    "guides": "ERR_GUIDE_NOT_FOUND",
    "trip_bookings": "ERR_BOOKING_NOT_FOUND",
    "trade_ins": "ERR_TRADE_IN_NOT_FOUND",
    "repair_orders": "ERR_REPAIR_ORDER_NOT_FOUND",
    "special_orders": "ERR_SPECIAL_ORDER_NOT_FOUND",
    "purchases": "ERR_PURCHASE_NOT_FOUND",
    "declarations": "ERR_DECLARATION_NOT_FOUND",
    "passes": "ERR_PASS_NOT_FOUND",
}


def lookup(coll_name, _id):
    coll = getattr(store, coll_name)
    ent = coll.get(_id)
    if ent is None:
        raise err(_NOT_FOUND[coll_name], "%s not found" % _id)
    return ent


# ==========================================================================
# Pagination + list serialization
# ==========================================================================


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate_and_serialize(items, serializer):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda e: (e.get("created_at", ""), e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    data = [serializer(e) for e in page]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok(data, 200, pagination=pagination, is_array=True)


# ==========================================================================
# Numeric helpers
# ==========================================================================


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_mul(amount, rate):
    return int((Decimal(amount) * Decimal(str(rate))).to_integral_value(rounding=ROUND_FLOOR))


def floor_prod(base, *factors):
    val = Decimal(base)
    for f in factors:
        val = val * Decimal(str(f))
    return int(val.to_integral_value(rounding=ROUND_FLOOR))


# ==========================================================================
# Calculation constants
# ==========================================================================
JOIN_FEE = {"BASIC": 3000, "PREMIER": 12000}
TIER_RENTAL_DISCOUNT = {"BASIC": Decimal("0.00"), "PREMIER": Decimal("0.10")}
PEAK_START = store._parse_instant("2026-06-01T00:00:00Z")
PEAK_END = store._parse_instant("2026-09-01T00:00:00Z")
PEAK_MULTIPLIER = Decimal("1.25")
MAX_REDEEM_PCT = Decimal("0.50")
POINTS_PER_CENT = Decimal("0.01")
PROVISIONAL_RATE = Decimal("0.05")
MIN_ELIGIBLE_SPEND_CENTS = 100000
GRADE_FACTOR = {"A": Decimal("0.50"), "B": Decimal("0.35"), "C": Decimal("0.20")}
CASH_FACTOR = Decimal("0.80")
CREDIT_FACTOR = Decimal("1.00")
MAX_TRADE_IN_ROUNDS = 3
SPECIAL_ORDER_DEPOSIT_PCT = Decimal("0.20")
WARRANTY_DAYS = 365
TURNAROUND_BUFFER_DAYS = 1


# ==========================================================================
# Derived aggregates
# ==========================================================================


def loyalty_balance(member_id):
    return sum(e["delta"] for e in store.loyalty_ledger.values() if e["member_id"] == member_id)


def eligible_spend(member_id):
    year = store.clock.now().year
    total = 0
    for p in store.purchases.values():
        if p["member_id"] != member_id:
            continue
        if p["status"] != "COMPLETED":
            continue
        if p["_created_dt"].year != year:
            continue
        total += p["eligible_spend_cents"]
    return total


def seats_confirmed(trip_id):
    return sum(
        1
        for b in store.trip_bookings.values()
        if b["trip_id"] == trip_id and b["status"] in ("CONFIRMED", "CHECKED_IN")
    )


def pass_coverage(p):
    if p["voided"]:
        return "VOID"
    clock = store.clock.now()
    vf = store._parse_instant(p["valid_from"])
    vt = store._parse_instant(p["valid_to"])
    if clock < vf:
        return "PENDING"
    if clock < vt:
        return "ACTIVE"
    return "EXPIRED"


def append_ledger(member_id, delta, reason, ref_id=None):
    entry = {
        "member_id": member_id,
        "delta": delta,
        "reason": reason,
        "ref_id": ref_id,
    }
    store.stamp_new(entry, common=False)
    store.loyalty_ledger[entry["id"]] = entry
    return entry


# ==========================================================================
# Serializers
# ==========================================================================


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_member(e):
    d = {
        "email": e["email"],
        "full_name": e["full_name"],
        "membership_tier": e["membership_tier"],
        "membership_status": e["membership_status"],
        "join_fee_cents": e["join_fee_cents"],
        "loyalty_points_balance": loyalty_balance(e["id"]),
        "eligible_spend_cents": eligible_spend(e["id"]),
        "wallet_credit_cents": e["wallet_credit_cents"],
    }
    d.update(_common(e))
    return d


def ser_product(e):
    d = {
        "sku": e["sku"],
        "name": e["name"],
        "category": e["category"],
        "retail_price_cents": e["retail_price_cents"],
        "tax_rate": e["tax_rate"],
        "replacement_value_cents": e["replacement_value_cents"],
        "is_rentable": e["is_rentable"],
        "base_daily_rate_cents": e["base_daily_rate_cents"],
    }
    d.update(_common(e))
    return d


def ser_rental_unit(e):
    d = {
        "product_id": e["product_id"],
        "asset_tag": e["asset_tag"],
        "status": e["status"],
        "condition": e["condition"],
    }
    d.update(_common(e))
    return d


def ser_reservation(e):
    d = {
        "member_id": e["member_id"],
        "rental_unit_id": e["rental_unit_id"],
        "product_id": e["product_id"],
        "start_date": e["start_date"],
        "end_date": e["end_date"],
        "rental_days": e["rental_days"],
        "status": e["status"],
        "rental_fee_cents": e["rental_fee_cents"],
    }
    d.update(_common(e))
    return d


def ser_trip(e):
    d = {
        "title": e["title"],
        "guide_id": e["guide_id"],
        "start_time": e["start_time"],
        "end_time": e["end_time"],
        "capacity": e["capacity"],
        "seats_confirmed": seats_confirmed(e["id"]),
        "price_cents": e["price_cents"],
        "required_certification": e["required_certification"],
        "status": e["status"],
    }
    d.update(_common(e))
    return d


def ser_guide(e):
    d = {
        "full_name": e["full_name"],
        "certifications": e["certifications"],
        "status": e["status"],
    }
    d.update(_common(e))
    return d


def ser_booking(e):
    d = {
        "trip_id": e["trip_id"],
        "member_id": e["member_id"],
        "price_paid_cents": e["price_paid_cents"],
        "points_redeemed": e["points_redeemed"],
        "status": e["status"],
    }
    d.update(_common(e))
    return d


def ser_trade_in(e):
    d = {
        "member_id": e["member_id"],
        "product_id": e["product_id"],
        "condition_grade": e["condition_grade"],
        "status": e["status"],
        "offered_cash_cents": e["offered_cash_cents"],
        "offered_credit_cents": e["offered_credit_cents"],
        "counter_ask_cents": e["counter_ask_cents"],
        "rounds": e["rounds"],
        "accepted_payout_type": e["accepted_payout_type"],
        "accepted_payout_cents": e["accepted_payout_cents"],
    }
    d.update(_common(e))
    return d


def ser_repair(e):
    d = {
        "member_id": e["member_id"],
        "product_id": e["product_id"],
        "rental_unit_id": e["rental_unit_id"],
        "purchase_date": e["purchase_date"],
        "repair_stage": e["repair_stage"],
        "billing_stage": e["billing_stage"],
        "warranty_status": e["warranty_status"],
        "labor_cents": e["labor_cents"],
        "parts_cents": e["parts_cents"],
        "billed_cents": e["billed_cents"],
    }
    d.update(_common(e))
    return d


def ser_pass(e):
    d = {
        "member_id": e["member_id"],
        "pass_type": e["pass_type"],
        "valid_from": e["valid_from"],
        "valid_to": e["valid_to"],
        "price_cents": e["price_cents"],
        "coverage_status": pass_coverage(e),
        "voided": e["voided"],
    }
    d.update(_common(e))
    return d


def ser_special_order(e):
    d = {
        "member_id": e["member_id"],
        "product_id": e["product_id"],
        "quantity": e["quantity"],
        "status": e["status"],
        "quoted_price_cents": e["quoted_price_cents"],
        "deposit_cents": e["deposit_cents"],
    }
    d.update(_common(e))
    return d


def ser_purchase(e):
    d = {
        "member_id": e["member_id"],
        "line_items": e["line_items"],
        "points_redeemed": e["points_redeemed"],
        "subtotal_cents": e["subtotal_cents"],
        "tax_cents": e["tax_cents"],
        "loyalty_redemption_cents": e["loyalty_redemption_cents"],
        "total_cents": e["total_cents"],
        "loyalty_points_earned": e["loyalty_points_earned"],
        "eligible_spend_cents": e["eligible_spend_cents"],
        "status": e["status"],
    }
    d.update(_common(e))
    return d


def ser_declaration(e):
    d = {
        "year": e["year"],
        "declared_rate": e["declared_rate"],
        "status": e["status"],
        "total_payout_cents": e["total_payout_cents"],
        "payouts": e["payouts"],
    }
    d.update(_common(e))
    return d


def ser_ledger(e):
    return {
        "id": e["id"],
        "member_id": e["member_id"],
        "delta": e["delta"],
        "reason": e["reason"],
        "ref_id": e["ref_id"],
        "created_at": e["created_at"],
    }
