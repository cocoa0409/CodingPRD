import os
import uuid
import random
import string
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =====================================================================
# Constants
# =====================================================================
ROLES = {"AccountHolder", "StudioOperator", "PlatformAdmin"}

PERIOD_DAYS = 30
REMINDER_BUFFER_DAYS = 2

SUBSCRIPTION_TIERS = {
    "FREE": {"monthly_card_credits": 0, "monthly_fee_cents": 0, "discount_pct": Decimal("0.0")},
    "PLUS": {"monthly_card_credits": 4, "monthly_fee_cents": 1200, "discount_pct": Decimal("0.10")},
    "PRO": {"monthly_card_credits": 12, "monthly_fee_cents": 3000, "discount_pct": Decimal("0.20")},
}

POSTAGE_TIERS = [
    (30, 150),
    (60, 250),
    (120, 450),
    (2147483647, 800),
]

REGION_TAX_RATES = {
    "CA": Decimal("0.0725"),
    "NY": Decimal("0.08875"),
    "TX": Decimal("0.0625"),
    "WA": Decimal("0.065"),
}
DEFAULT_TAX_RATE = Decimal("0.0")

CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Enums
TIER_ENUM = {"FREE", "PLUS", "PRO"}
CREDIT_REASON_ENUM = {"SUBSCRIPTION_GRANT", "PRORATION_GRANT", "ORDER_HOLD", "ORDER_REFUND", "MANUAL_ADJUST"}
OCCASION_ENUM = {"BIRTHDAY", "ANNIVERSARY", "HOLIDAY", "CUSTOM"}
RECURRENCE_ENUM = {"NONE", "ANNUAL"}
CARD_CATEGORY_ENUM = {"BIRTHDAY", "THANK_YOU", "HOLIDAY", "SYMPATHY", "CUSTOM"}
GIFT_KIND_ENUM = {"GIFT_CARD", "FLOWERS", "CHOCOLATE", "CUSTOM_NOTE"}
FONT_ENUM = {"SCRIPT", "PRINT", "CASUAL"}
CARRIER_ENUM = {"USPS", "UPS"}
VERIFY_RESULT_ENUM = {"VERIFIED", "UNDELIVERABLE"}
SHIPMENT_ADVANCE_ENUM = {"IN_TRANSIT", "DELIVERED", "RETURNED"}

# =====================================================================
# In-memory store (starts EMPTY on every boot — no seeding)
# =====================================================================
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.accounts = {}
        self.subscriptions = {}
        self.credit_txns = {}
        self.contacts = {}
        self.important_dates = {}
        self.cards = {}
        self.gift_items = {}
        self.artists = {}
        self.orders = {}
        self.proofs = {}
        self.assignments = {}
        self.shipments = {}
        self.clock = parse_dt(CLOCK_DEFAULT)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# =====================================================================
# Datetime helpers
# =====================================================================
def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    return datetime.now(timezone.utc)


def add_years(dt, n):
    try:
        return dt.replace(year=dt.year + n)
    except ValueError:
        # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + n, day=28)


# =====================================================================
# Errors
# =====================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, status, message=""):
    raise ApiError(error_id, status, message)


NOT_FOUND = {
    "account": "ERR_ACCOUNT_NOT_FOUND",
    "subscription": "ERR_SUBSCRIPTION_NOT_FOUND",
    "contact": "ERR_CONTACT_NOT_FOUND",
    "important_date": "ERR_IMPORTANT_DATE_NOT_FOUND",
    "card": "ERR_CARD_NOT_FOUND",
    "gift_item": "ERR_GIFT_ITEM_NOT_FOUND",
    "artist": "ERR_ARTIST_NOT_FOUND",
    "order": "ERR_ORDER_NOT_FOUND",
    "proof": "ERR_PROOF_NOT_FOUND",
    "shipment": "ERR_SHIPMENT_NOT_FOUND",
}


# =====================================================================
# Response envelope
# =====================================================================
def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": fmt_dt(wall_now()),
    }


def to_json(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def object_response(data, code=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), code


def array_response(items, code=200, pagination=None):
    meta = meta_base()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# =====================================================================
# Auth / RBAC helpers
# =====================================================================
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")


def check_owner(role, uid, account_id):
    if role == "AccountHolder" and uid != account_id:
        err("ERR_UNAUTHORIZED", 403, "Account holder does not own this resource.")


# =====================================================================
# Body / validation helpers
# =====================================================================
def get_body():
    if request.data:
        body = request.get_json(silent=True)
        if body is None:
            err("ERR_VALIDATION", 400, "Malformed JSON body.")
        if not isinstance(body, dict):
            err("ERR_VALIDATION", 400, "Body must be a JSON object.")
        return body
    return {}


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            err("ERR_VALIDATION", 400, f"Missing required field: {f}")


def require_enum(value, allowed, field):
    if value not in allowed:
        err("ERR_VALIDATION", 400, f"Invalid value for {field}.")


def require_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_VALIDATION", 400, f"Field {field} must be an integer.")
    if minimum is not None and value < minimum:
        err("ERR_VALIDATION", 400, f"Field {field} must be >= {minimum}.")
    return value


def parse_dt_field(value, field):
    try:
        return parse_dt(value)
    except Exception:
        err("ERR_VALIDATION", 400, f"Field {field} must be an ISO 8601 datetime.")


# Existence resolvers
def get_or_404(coll, _id, kind):
    ent = coll.get(_id)
    if ent is None:
        err(NOT_FOUND[kind], 404, f"{kind} not found.")
    return ent


# =====================================================================
# Entity construction
# =====================================================================
def base_entity(extra):
    now = wall_now()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    ent.update(extra)
    return ent


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = wall_now()


# =====================================================================
# Credit ledger
# =====================================================================
def account_balance(account_id):
    return sum(t["delta"] for t in db.credit_txns.values() if t["account_id"] == account_id)


def add_credit_txn(account_id, delta, reason):
    account = db.accounts[account_id]
    new_total = account_balance(account_id) + delta
    txn = {
        "id": str(uuid.uuid4()),
        "created_at": wall_now(),
        "_seq": db.next_seq(),
        "account_id": account_id,
        "delta": delta,
        "reason": reason,
        "balance_after": new_total,
    }
    db.credit_txns[txn["id"]] = txn
    account["card_credit_balance"] = new_total
    return txn


def recompute_artist_count(artist):
    cnt = sum(
        1 for a in db.assignments.values()
        if a["artist_id"] == artist["id"] and a["status"] == "RESERVED"
    )
    artist["reserved_assignment_count"] = cnt
    touch(artist)


# =====================================================================
# Pagination
# =====================================================================
def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "limit must be an integer.")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "offset must be an integer.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination


def sort_seq(items):
    return sorted(items, key=lambda e: e["_seq"])


# =====================================================================
# Postage / money calculations
# =====================================================================
def compute_postage(total_weight):
    for max_g, cents in POSTAGE_TIERS:
        if total_weight <= max_g:
            return cents
    return POSTAGE_TIERS[-1][1]


def round_half_up(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def order_total_weight(order):
    card = db.cards[order["card_id"]]
    total = card["weight_grams"]
    if order.get("gift_item_id"):
        gift = db.gift_items[order["gift_item_id"]]
        total += gift["weight_grams"] * order["gift_quantity"]
    return total


def order_gift_price(order):
    if order.get("gift_item_id"):
        gift = db.gift_items[order["gift_item_id"]]
        return gift["price_cents"] * order["gift_quantity"]
    return 0


def active_subscription(account_id):
    subs = [s for s in db.subscriptions.values()
            if s["account_id"] == account_id and s["status"] == "ACTIVE"]
    subs = sort_seq(subs)
    return subs[-1] if subs else None


def compute_estimate(order):
    total_weight = order_total_weight(order)
    postage = compute_postage(total_weight)
    gift_price = order_gift_price(order)
    order["postage_cents"] = postage
    order["estimated_total_cents"] = postage + gift_price
    order["gift_discount_cents"] = 0
    order["tax_cents"] = 0
    order["final_total_cents"] = None


def compute_final(order):
    total_weight = order_total_weight(order)
    postage = compute_postage(total_weight)
    gift_price = order_gift_price(order)

    sub = active_subscription(order["account_id"])
    pct = Decimal(str(sub["discount_pct"])) if sub else Decimal("0.0")

    gift_discount = round_half_up(Decimal(gift_price) * pct)
    taxable = gift_price - gift_discount

    contact = db.contacts[order["contact_id"]]
    rate = REGION_TAX_RATES.get(contact["region"], DEFAULT_TAX_RATE)
    tax = round_half_up(Decimal(taxable) * rate)

    order["postage_cents"] = postage
    order["gift_discount_cents"] = gift_discount
    order["tax_cents"] = tax
    order["final_total_cents"] = postage + (gift_price - gift_discount) + tax


# =====================================================================
# Root health
# =====================================================================
@app.route("/", methods=["GET"])
def root():
    return jsonify({"status": "ok"}), 200


# =====================================================================
# Accounts
# =====================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["email", "display_name"])
    account = base_entity({
        "email": body["email"],
        "display_name": body["display_name"],
        "status": "ACTIVE",
        "card_credit_balance": 0,
    })
    db.accounts[account["id"]] = account
    return object_response(to_json(account), 201)


@app.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "AccountHolder"})
    account = get_or_404(db.accounts, account_id, "account")
    check_owner(role, uid, account_id)
    return object_response(to_json(account))


@app.route("/accounts/<account_id>/subscriptions", methods=["POST"])
def create_subscription(account_id):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "AccountHolder"})
    body = get_body()
    require_fields(body, ["tier"])
    require_enum(body["tier"], TIER_ENUM, "tier")
    account = get_or_404(db.accounts, account_id, "account")
    check_owner(role, uid, account_id)

    tier = body["tier"]
    spec = SUBSCRIPTION_TIERS[tier]
    now = db.clock
    period_end = now + timedelta(days=PERIOD_DAYS)
    sub = base_entity({
        "account_id": account_id,
        "tier": tier,
        "monthly_card_credits": spec["monthly_card_credits"],
        "monthly_fee_cents": spec["monthly_fee_cents"],
        "discount_pct": float(spec["discount_pct"]),
        "status": "ACTIVE",
        "current_period_start": now,
        "current_period_end": period_end,
        "next_renewal_at": period_end,
    })
    db.subscriptions[sub["id"]] = sub

    add_credit_txn(account_id, spec["monthly_card_credits"], "SUBSCRIPTION_GRANT")
    touch(account)
    return object_response(to_json(sub), 201)


@app.route("/accounts/<account_id>/subscription", methods=["GET"])
def get_account_subscription(account_id):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "AccountHolder"})
    account = get_or_404(db.accounts, account_id, "account")
    check_owner(role, uid, account_id)
    subs = sort_seq([s for s in db.subscriptions.values() if s["account_id"] == account_id])
    return array_response([to_json(s) for s in subs])


@app.route("/subscriptions/<sub_id>/change-tier", methods=["POST"])
def change_tier(sub_id):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "AccountHolder"})
    body = get_body()
    require_fields(body, ["tier"])
    require_enum(body["tier"], TIER_ENUM, "tier")
    sub = get_or_404(db.subscriptions, sub_id, "subscription")
    check_owner(role, uid, sub["account_id"])

    if sub["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Subscription is not ACTIVE.")

    new_tier = body["tier"]
    spec = SUBSCRIPTION_TIERS[new_tier]

    delta_seconds = (sub["current_period_end"] - db.clock).total_seconds()
    days_remaining = max(0, math.ceil(delta_seconds / 86400.0))
    new_credits = spec["monthly_card_credits"]
    grant = (new_credits * days_remaining + PERIOD_DAYS - 1) // PERIOD_DAYS  # ceil

    sub["tier"] = new_tier
    sub["monthly_card_credits"] = spec["monthly_card_credits"]
    sub["monthly_fee_cents"] = spec["monthly_fee_cents"]
    sub["discount_pct"] = float(spec["discount_pct"])
    touch(sub)

    account = db.accounts[sub["account_id"]]
    add_credit_txn(sub["account_id"], grant, "PRORATION_GRANT")
    touch(account)
    return object_response(to_json(sub))


@app.route("/subscriptions/<sub_id>/cancel", methods=["POST"])
def cancel_subscription(sub_id):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "AccountHolder"})
    sub = get_or_404(db.subscriptions, sub_id, "subscription")
    check_owner(role, uid, sub["account_id"])
    if sub["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Subscription is not ACTIVE.")
    sub["status"] = "CANCELLED"
    touch(sub)
    return object_response(to_json(sub))


@app.route("/accounts/<account_id>/credit-adjustments", methods=["POST"])
def credit_adjustment(account_id):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["delta"])
    require_int(body["delta"], "delta")
    reason = body.get("reason", "MANUAL_ADJUST")
    require_enum(reason, CREDIT_REASON_ENUM, "reason")
    account = get_or_404(db.accounts, account_id, "account")

    txn = add_credit_txn(account_id, body["delta"], reason)
    touch(account)
    return object_response(to_json(txn), 201)


@app.route("/accounts/<account_id>/credit-transactions", methods=["GET"])
def list_credit_transactions(account_id):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "AccountHolder"})
    account = get_or_404(db.accounts, account_id, "account")
    check_owner(role, uid, account_id)
    txns = [t for t in db.credit_txns.values() if t["account_id"] == account_id]
    txns = sorted(txns, key=lambda e: e["_seq"], reverse=True)  # newest first
    page, pagination = paginate(txns)
    return array_response([to_json(t) for t in page], pagination=pagination)


# =====================================================================
# Contacts
# =====================================================================
CONTACT_REQUIRED = ["account_id", "full_name", "address_line1", "city", "region", "postal_code", "country_code"]


@app.route("/contacts", methods=["POST"])
def create_contact():
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "PlatformAdmin"})
    body = get_body()
    require_fields(body, CONTACT_REQUIRED)
    account = get_or_404(db.accounts, body["account_id"], "account")
    check_owner(role, uid, body["account_id"])
    contact = base_entity({
        "account_id": body["account_id"],
        "full_name": body["full_name"],
        "address_line1": body["address_line1"],
        "address_line2": body.get("address_line2"),
        "city": body["city"],
        "region": body["region"],
        "postal_code": body["postal_code"],
        "country_code": body["country_code"],
        "address_status": "UNVERIFIED",
    })
    db.contacts[contact["id"]] = contact
    return object_response(to_json(contact), 201)


@app.route("/accounts/<account_id>/contacts", methods=["GET"])
def list_account_contacts(account_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "PlatformAdmin"})
    account = get_or_404(db.accounts, account_id, "account")
    check_owner(role, uid, account_id)
    items = [c for c in db.contacts.values() if c["account_id"] == account_id]
    status_filter = request.args.get("address_status")
    if status_filter:
        items = [c for c in items if c["address_status"] == status_filter]
    items = sort_seq(items)
    page, pagination = paginate(items)
    return array_response([to_json(c) for c in page], pagination=pagination)


@app.route("/contacts/<contact_id>", methods=["GET"])
def get_contact(contact_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "StudioOperator", "PlatformAdmin"})
    contact = get_or_404(db.contacts, contact_id, "contact")
    check_owner(role, uid, contact["account_id"])
    return object_response(to_json(contact))


@app.route("/accounts/<account_id>/contacts/bulk-import", methods=["POST"])
def bulk_import(account_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "PlatformAdmin"})
    body = get_body()
    require_fields(body, ["source", "rows"])
    rows = body["rows"]
    if not isinstance(rows, list):
        err("ERR_VALIDATION", 400, "rows must be an array.")
    account = get_or_404(db.accounts, account_id, "account")
    check_owner(role, uid, account_id)
    if len(rows) == 0:
        err("ERR_EMPTY_IMPORT", 422, "Import rows array is empty.")

    row_required = ["full_name", "address_line1", "city", "region", "postal_code", "country_code"]
    imported = 0
    skipped = 0
    contact_ids = []
    for row in rows:
        if not isinstance(row, dict) or any(row.get(f) is None for f in row_required):
            skipped += 1
            continue
        contact = base_entity({
            "account_id": account_id,
            "full_name": row["full_name"],
            "address_line1": row["address_line1"],
            "address_line2": row.get("address_line2"),
            "city": row["city"],
            "region": row["region"],
            "postal_code": row["postal_code"],
            "country_code": row["country_code"],
            "address_status": "UNVERIFIED",
        })
        db.contacts[contact["id"]] = contact
        contact_ids.append(contact["id"])
        imported += 1
    data = {"imported_count": imported, "skipped_count": skipped, "contact_ids": contact_ids}
    return object_response(data, 201)


@app.route("/contacts/<contact_id>/verify-address", methods=["POST"])
def verify_address(contact_id):
    uid, role = require_auth()
    require_role(role, {"StudioOperator", "PlatformAdmin"})
    body = get_body()
    require_fields(body, ["result"])
    require_enum(body["result"], VERIFY_RESULT_ENUM, "result")
    contact = get_or_404(db.contacts, contact_id, "contact")
    result = body["result"]
    cur = contact["address_status"]
    if result == "VERIFIED":
        if cur != "UNVERIFIED":
            err("ERR_INVALID_STATE", 409, "Cannot verify from current state.")
        contact["address_status"] = "VERIFIED"
    else:  # UNDELIVERABLE
        if cur not in ("UNVERIFIED", "VERIFIED"):
            err("ERR_INVALID_STATE", 409, "Cannot mark undeliverable from current state.")
        contact["address_status"] = "UNDELIVERABLE"
    touch(contact)
    return object_response(to_json(contact))


# =====================================================================
# Important Dates
# =====================================================================
def reminder_window(event_date, lead_days):
    return (event_date - timedelta(days=lead_days), event_date)


@app.route("/contacts/<contact_id>/important-dates", methods=["POST"])
def create_important_date(contact_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "PlatformAdmin"})
    body = get_body()
    require_fields(body, ["occasion_type", "event_date", "lead_days"])
    require_enum(body["occasion_type"], OCCASION_ENUM, "occasion_type")
    event_date = parse_dt_field(body["event_date"], "event_date")
    lead_days = require_int(body["lead_days"], "lead_days", minimum=0)
    recurrence = body.get("recurrence", "NONE")
    require_enum(recurrence, RECURRENCE_ENUM, "recurrence")
    auto_send = body.get("auto_send", False)
    if not isinstance(auto_send, bool):
        err("ERR_VALIDATION", 400, "auto_send must be a boolean.")
    default_card_id = body.get("default_card_id")

    contact = get_or_404(db.contacts, contact_id, "contact")
    check_owner(role, uid, contact["account_id"])
    if default_card_id is not None:
        get_or_404(db.cards, default_card_id, "card")

    # priority 13: reminder-window overlap
    new_win = reminder_window(event_date, lead_days)
    for imp in db.important_dates.values():
        if (imp["contact_id"] == contact_id and imp["status"] == "ACTIVE"
                and imp["occasion_type"] == body["occasion_type"]):
            ex_win = reminder_window(imp["event_date"], imp["lead_days"])
            separation = max(ex_win[0] - new_win[1], new_win[0] - ex_win[1])
            if separation < timedelta(days=REMINDER_BUFFER_DAYS):
                err("ERR_REMINDER_WINDOW_OVERLAP", 409, "Reminder window overlaps an existing reminder.")

    # priority 17: auto_send requires default_card_id
    if auto_send and default_card_id is None:
        err("ERR_AUTO_SEND_CARD_REQUIRED", 422, "auto_send requires default_card_id.")

    next_trigger = event_date - timedelta(days=lead_days)
    imp = base_entity({
        "contact_id": contact_id,
        "occasion_type": body["occasion_type"],
        "event_date": event_date,
        "lead_days": lead_days,
        "recurrence": recurrence,
        "auto_send": auto_send,
        "default_card_id": default_card_id,
        "status": "ACTIVE",
        "next_trigger_at": next_trigger,
    })
    db.important_dates[imp["id"]] = imp
    return object_response(to_json(imp), 201)


@app.route("/important-dates/<imp_id>", methods=["GET"])
def get_important_date(imp_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "PlatformAdmin"})
    imp = get_or_404(db.important_dates, imp_id, "important_date")
    contact = db.contacts[imp["contact_id"]]
    check_owner(role, uid, contact["account_id"])
    return object_response(to_json(imp))


@app.route("/important-dates", methods=["GET"])
def list_important_dates():
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "PlatformAdmin"})
    items = list(db.important_dates.values())
    if role == "AccountHolder":
        items = [i for i in items if db.contacts[i["contact_id"]]["account_id"] == uid]
    contact_id = request.args.get("contact_id")
    if contact_id:
        items = [i for i in items if i["contact_id"] == contact_id]
    default_card_id = request.args.get("default_card_id")
    if default_card_id:
        items = [i for i in items if i.get("default_card_id") == default_card_id]
    status_f = request.args.get("status")
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    items = sort_seq(items)
    page, pagination = paginate(items)
    return array_response([to_json(i) for i in page], pagination=pagination)


@app.route("/important-dates/<imp_id>/archive", methods=["POST"])
def archive_important_date(imp_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "PlatformAdmin"})
    imp = get_or_404(db.important_dates, imp_id, "important_date")
    contact = db.contacts[imp["contact_id"]]
    check_owner(role, uid, contact["account_id"])
    if imp["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Important date is not ACTIVE.")
    imp["status"] = "ARCHIVED"
    touch(imp)
    return object_response(to_json(imp))


# =====================================================================
# Cards
# =====================================================================
@app.route("/cards", methods=["POST"])
def create_card():
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "StudioOperator"})
    body = get_body()
    require_fields(body, ["sku", "title", "category", "base_price_cents", "weight_grams"])
    require_enum(body["category"], CARD_CATEGORY_ENUM, "category")
    require_int(body["base_price_cents"], "base_price_cents", minimum=0)
    require_int(body["weight_grams"], "weight_grams", minimum=0)
    card = base_entity({
        "sku": body["sku"],
        "title": body["title"],
        "category": body["category"],
        "base_price_cents": body["base_price_cents"],
        "weight_grams": body["weight_grams"],
        "status": "ACTIVE",
    })
    db.cards[card["id"]] = card
    return object_response(to_json(card), 201)


@app.route("/cards/<card_id>", methods=["GET"])
def get_card(card_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "StudioOperator", "PlatformAdmin"})
    card = get_or_404(db.cards, card_id, "card")
    return object_response(to_json(card))


@app.route("/cards/<card_id>/retire", methods=["POST"])
def retire_card(card_id):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "StudioOperator"})
    card = get_or_404(db.cards, card_id, "card")
    if card["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Card is not ACTIVE.")
    card["status"] = "RETIRED"
    touch(card)
    return object_response(to_json(card))


# =====================================================================
# Gift Items
# =====================================================================
@app.route("/gift-items", methods=["POST"])
def create_gift_item():
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "StudioOperator"})
    body = get_body()
    require_fields(body, ["sku", "title", "kind", "price_cents", "weight_grams"])
    require_enum(body["kind"], GIFT_KIND_ENUM, "kind")
    require_int(body["price_cents"], "price_cents", minimum=0)
    require_int(body["weight_grams"], "weight_grams", minimum=0)
    gift = base_entity({
        "sku": body["sku"],
        "title": body["title"],
        "kind": body["kind"],
        "price_cents": body["price_cents"],
        "weight_grams": body["weight_grams"],
        "status": "ACTIVE",
    })
    db.gift_items[gift["id"]] = gift
    return object_response(to_json(gift), 201)


@app.route("/gift-items/<gift_id>/retire", methods=["POST"])
def retire_gift_item(gift_id):
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "StudioOperator"})
    gift = get_or_404(db.gift_items, gift_id, "gift_item")
    if gift["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Gift item is not ACTIVE.")
    gift["status"] = "RETIRED"
    touch(gift)
    return object_response(to_json(gift))


# =====================================================================
# Artists
# =====================================================================
@app.route("/artists", methods=["POST"])
def create_artist():
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin", "StudioOperator"})
    body = get_body()
    require_fields(body, ["name", "daily_capacity", "region_code"])
    require_int(body["daily_capacity"], "daily_capacity", minimum=1)
    artist = base_entity({
        "name": body["name"],
        "region_code": body["region_code"],
        "daily_capacity": body["daily_capacity"],
        "status": "AVAILABLE",
        "reserved_assignment_count": 0,
    })
    db.artists[artist["id"]] = artist
    return object_response(to_json(artist), 201)


@app.route("/artists/<artist_id>", methods=["GET"])
def get_artist(artist_id):
    uid, role = require_auth()
    require_role(role, {"StudioOperator", "PlatformAdmin"})
    artist = get_or_404(db.artists, artist_id, "artist")
    return object_response(to_json(artist))


# =====================================================================
# Orders
# =====================================================================
def build_order(account_id, contact_id, card_id, message_text, scheduled_send_at,
                font_style="SCRIPT", gift_item_id=None, gift_quantity=0, important_date_id=None):
    order = base_entity({
        "account_id": account_id,
        "contact_id": contact_id,
        "card_id": card_id,
        "gift_item_id": gift_item_id,
        "gift_quantity": gift_quantity,
        "important_date_id": important_date_id,
        "artist_id": None,
        "message_text": message_text,
        "font_style": font_style,
        "scheduled_send_at": scheduled_send_at,
        "status": "DRAFT",
        "credit_status": "NONE",
        "estimated_total_cents": 0,
        "postage_cents": 0,
        "gift_discount_cents": 0,
        "tax_cents": 0,
        "final_total_cents": None,
        "mailed_at": None,
        "delivered_at": None,
    })
    compute_estimate(order)
    db.orders[order["id"]] = order
    return order


@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "PlatformAdmin"})
    body = get_body()
    require_fields(body, ["account_id", "contact_id", "card_id", "message_text", "scheduled_send_at"])
    font_style = body.get("font_style", "SCRIPT")
    require_enum(font_style, FONT_ENUM, "font_style")
    scheduled = parse_dt_field(body["scheduled_send_at"], "scheduled_send_at")
    gift_item_id = body.get("gift_item_id")
    gift_quantity = body.get("gift_quantity", 0)
    if gift_quantity is None:
        gift_quantity = 0
    require_int(gift_quantity, "gift_quantity", minimum=0)

    # existence (priority 3): account, contact, card, gift
    account = get_or_404(db.accounts, body["account_id"], "account")
    contact = get_or_404(db.contacts, body["contact_id"], "contact")
    card = get_or_404(db.cards, body["card_id"], "card")
    gift = None
    if gift_item_id is not None:
        gift = get_or_404(db.gift_items, gift_item_id, "gift_item")

    # ownership
    check_owner(role, uid, body["account_id"])

    # priority 5: card active
    if card["status"] != "ACTIVE":
        err("ERR_CARD_RETIRED", 409, "Card is retired.")
    # priority 6: gift active
    if gift is not None and gift["status"] != "ACTIVE":
        err("ERR_GIFT_ITEM_RETIRED", 409, "Gift item is retired.")
    # priority 15: gift_quantity >= 1 when gift present
    if gift_item_id is not None and gift_quantity < 1:
        err("ERR_GIFT_QUANTITY_INVALID", 422, "gift_quantity must be >= 1 when gift present.")

    order = build_order(
        body["account_id"], body["contact_id"], body["card_id"], body["message_text"],
        scheduled, font_style, gift_item_id, gift_quantity, body.get("important_date_id")
    )
    return object_response(to_json(order), 201)


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "StudioOperator", "PlatformAdmin"})
    order = get_or_404(db.orders, order_id, "order")
    check_owner(role, uid, order["account_id"])
    return object_response(to_json(order))


@app.route("/orders", methods=["GET"])
def list_orders():
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "StudioOperator", "PlatformAdmin"})
    items = list(db.orders.values())
    if role == "AccountHolder":
        items = [o for o in items if o["account_id"] == uid]
    for key in ["account_id", "contact_id", "card_id", "gift_item_id", "artist_id", "important_date_id", "status"]:
        val = request.args.get(key)
        if val:
            items = [o for o in items if o.get(key) == val]
    items = sort_seq(items)
    page, pagination = paginate(items)
    return array_response([to_json(o) for o in page], pagination=pagination)


@app.route("/orders/<order_id>/submit", methods=["POST"])
def submit_order(order_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder"})
    body = get_body()
    require_fields(body, ["expected_account_version"])
    require_int(body["expected_account_version"], "expected_account_version")
    order = get_or_404(db.orders, order_id, "order")
    check_owner(role, uid, order["account_id"])

    account = db.accounts[order["account_id"]]
    card = db.cards[order["card_id"]]
    contact = db.contacts[order["contact_id"]]

    # priority 4: state
    if order["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Order is not DRAFT.")
    # priority 5: card active
    if card["status"] != "ACTIVE":
        err("ERR_CARD_RETIRED", 409, "Card is retired.")
    # priority 7: address verified
    if contact["address_status"] != "VERIFIED":
        err("ERR_ADDRESS_NOT_VERIFIED", 409, "Contact address is not verified.")
    # priority 10: send date in future
    if not (order["scheduled_send_at"] > db.clock):
        err("ERR_SEND_DATE_IN_PAST", 422, "scheduled_send_at must be in the future.")
    # priority 18: sufficient credits
    if account["card_credit_balance"] < 1:
        err("ERR_INSUFFICIENT_CREDITS", 402, "Insufficient card credits.")
    # priority 19: OCC
    if body["expected_account_version"] != account["version"]:
        err("ERR_STALE_ACCOUNT_VERSION", 412, "Stale account version.")

    # side effects
    order["status"] = "PENDING_PROOF"
    order["credit_status"] = "HELD"
    add_credit_txn(order["account_id"], -1, "ORDER_HOLD")
    touch(account)
    touch(order)

    proof = base_entity({
        "order_id": order_id,
        "status": "PENDING",
        "proof_image_ref": "proofimg_" + uuid.uuid4().hex,
        "revision_count": 0,
        "reviewer_notes": None,
    })
    db.proofs[proof["id"]] = proof
    return object_response(to_json(order))


@app.route("/orders/<order_id>/assign-artist", methods=["POST"])
def assign_artist(order_id):
    uid, role = require_auth()
    require_role(role, {"StudioOperator"})
    body = get_body()
    require_fields(body, ["artist_id", "window_start", "window_end"])
    window_start = parse_dt_field(body["window_start"], "window_start")
    window_end = parse_dt_field(body["window_end"], "window_end")
    order = get_or_404(db.orders, order_id, "order")
    artist = get_or_404(db.artists, body["artist_id"], "artist")

    # priority 12: overlap with existing RESERVED windows for same artist (half-open)
    for a in db.assignments.values():
        if a["artist_id"] == artist["id"] and a["status"] == "RESERVED":
            if window_start < a["window_end"] and a["window_start"] < window_end:
                err("ERR_ARTIST_WINDOW_CONFLICT", 409, "Production window overlaps an existing reservation.")

    # priority 14: daily capacity
    same_date = window_start.date()
    reserved_on_date = sum(
        1 for a in db.assignments.values()
        if a["artist_id"] == artist["id"] and a["status"] == "RESERVED"
        and a["window_start"].date() == same_date
    )
    if reserved_on_date + 1 > artist["daily_capacity"]:
        err("ERR_ARTIST_CAPACITY_EXCEEDED", 409, "Artist daily capacity exceeded.")

    assignment = base_entity({
        "artist_id": artist["id"],
        "order_id": order_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "RESERVED",
    })
    db.assignments[assignment["id"]] = assignment
    order["artist_id"] = artist["id"]
    touch(order)
    recompute_artist_count(artist)
    return object_response(to_json(assignment), 201)


@app.route("/artist-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    uid, role = require_auth()
    require_role(role, {"StudioOperator", "PlatformAdmin"})
    a = db.assignments.get(assignment_id)
    if a is None:
        err("ERR_ORDER_NOT_FOUND", 404, "Assignment not found.")
    return object_response(to_json(a))


@app.route("/artist-assignments", methods=["GET"])
def list_assignments():
    uid, role = require_auth()
    require_role(role, {"StudioOperator", "PlatformAdmin"})
    items = list(db.assignments.values())
    for key in ["artist_id", "order_id", "status"]:
        val = request.args.get(key)
        if val:
            items = [a for a in items if a.get(key) == val]
    items = sort_seq(items)
    page, pagination = paginate(items)
    return array_response([to_json(a) for a in page], pagination=pagination)


@app.route("/orders/<order_id>/proofs", methods=["GET"])
def list_order_proofs(order_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "StudioOperator"})
    order = get_or_404(db.orders, order_id, "order")
    check_owner(role, uid, order["account_id"])
    items = sort_seq([p for p in db.proofs.values() if p["order_id"] == order_id])
    return array_response([to_json(p) for p in items])


# =====================================================================
# Proofs
# =====================================================================
def order_of_proof(proof):
    return db.orders[proof["order_id"]]


@app.route("/proofs/<proof_id>/approve", methods=["POST"])
def approve_proof(proof_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder"})
    proof = get_or_404(db.proofs, proof_id, "proof")
    order = order_of_proof(proof)
    check_owner(role, uid, order["account_id"])
    if proof["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Proof is not PENDING.")
    proof["status"] = "APPROVED"
    touch(proof)
    # cascade
    if order["status"] == "PENDING_PROOF":
        order["status"] = "PROOF_APPROVED"
        touch(order)
    return object_response(to_json(proof))


@app.route("/proofs/<proof_id>/request-changes", methods=["POST"])
def request_changes(proof_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder"})
    body = get_body()
    require_fields(body, ["reviewer_notes"])
    proof = get_or_404(db.proofs, proof_id, "proof")
    order = order_of_proof(proof)
    check_owner(role, uid, order["account_id"])
    if proof["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Proof is not PENDING.")
    proof["status"] = "CHANGES_REQUESTED"
    proof["revision_count"] += 1
    proof["reviewer_notes"] = body["reviewer_notes"]
    touch(proof)
    return object_response(to_json(proof))


@app.route("/proofs/<proof_id>/revise", methods=["POST"])
def revise_proof(proof_id):
    uid, role = require_auth()
    require_role(role, {"StudioOperator"})
    body = get_body()
    require_fields(body, ["proof_image_ref"])
    proof = get_or_404(db.proofs, proof_id, "proof")
    if proof["status"] != "CHANGES_REQUESTED":
        err("ERR_INVALID_STATE", 409, "Proof is not CHANGES_REQUESTED.")
    proof["status"] = "PENDING"
    proof["proof_image_ref"] = body["proof_image_ref"]
    touch(proof)
    return object_response(to_json(proof))


# =====================================================================
# Order lifecycle: schedule / produce / mail / cancel
# =====================================================================
def order_proof(order_id):
    proofs = [p for p in db.proofs.values() if p["order_id"] == order_id]
    proofs = sort_seq(proofs)
    return proofs[-1] if proofs else None


def order_reserved_assignment(order_id):
    for a in db.assignments.values():
        if a["order_id"] == order_id and a["status"] == "RESERVED":
            return a
    return None


@app.route("/orders/<order_id>/schedule", methods=["POST"])
def schedule_order(order_id):
    uid, role = require_auth()
    require_role(role, {"StudioOperator", "AccountHolder"})
    order = get_or_404(db.orders, order_id, "order")
    check_owner(role, uid, order["account_id"])
    contact = db.contacts[order["contact_id"]]

    if order["status"] != "PROOF_APPROVED":
        err("ERR_INVALID_STATE", 409, "Order is not PROOF_APPROVED.")
    # priority 7: address verified
    if contact["address_status"] != "VERIFIED":
        err("ERR_ADDRESS_NOT_VERIFIED", 409, "Contact address is not verified.")
    # priority 10: send date in future
    if not (order["scheduled_send_at"] > db.clock):
        err("ERR_SEND_DATE_IN_PAST", 422, "scheduled_send_at must be in the future.")

    order["status"] = "SCHEDULED"
    touch(order)
    return object_response(to_json(order))


@app.route("/orders/<order_id>/produce", methods=["POST"])
def produce_order(order_id):
    uid, role = require_auth()
    require_role(role, {"StudioOperator"})
    order = get_or_404(db.orders, order_id, "order")

    if order["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Order is not SCHEDULED.")
    proof = order_proof(order_id)
    # priority 8: proof approved
    if proof is None or proof["status"] != "APPROVED":
        err("ERR_PROOF_NOT_APPROVED", 409, "Order proof is not approved.")
    # priority 9: artist assigned
    assignment = order_reserved_assignment(order_id)
    if assignment is None:
        err("ERR_ARTIST_NOT_ASSIGNED", 409, "No reserved artist assignment for order.")
    # priority 11: clock reached scheduled_send_at
    if not (db.clock >= order["scheduled_send_at"]):
        err("ERR_TOO_EARLY_TO_PRODUCE", 409, "Too early to produce.")

    compute_final(order)
    order["status"] = "IN_PRODUCTION"
    order["credit_status"] = "SETTLED"
    touch(order)

    assignment["status"] = "COMPLETED"
    touch(assignment)
    artist = db.artists[assignment["artist_id"]]
    recompute_artist_count(artist)
    return object_response(to_json(order))


@app.route("/orders/<order_id>/mail", methods=["POST"])
def mail_order(order_id):
    uid, role = require_auth()
    require_role(role, {"StudioOperator"})
    body = get_body()
    carrier = body.get("carrier", "USPS")
    require_enum(carrier, CARRIER_ENUM, "carrier")
    order = get_or_404(db.orders, order_id, "order")

    if order["status"] != "IN_PRODUCTION":
        err("ERR_INVALID_STATE", 409, "Order is not IN_PRODUCTION.")
    proof = order_proof(order_id)
    if proof is None or proof["status"] != "APPROVED":
        err("ERR_PROOF_NOT_APPROVED", 409, "Order proof is not approved.")

    now = db.clock
    order["status"] = "MAILED"
    order["mailed_at"] = now
    touch(order)

    shipment = base_entity({
        "order_id": order_id,
        "carrier": carrier,
        "tracking_number": "TRK" + "".join(random.choices(string.digits, k=12)),
        "status": "LABEL_CREATED",
        "mailed_at": now,
        "delivered_at": None,
    })
    db.shipments[shipment["id"]] = shipment
    return object_response(to_json(order))


@app.route("/orders/<order_id>/shipment", methods=["GET"])
def get_order_shipment(order_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "StudioOperator"})
    order = get_or_404(db.orders, order_id, "order")
    check_owner(role, uid, order["account_id"])
    items = sort_seq([s for s in db.shipments.values() if s["order_id"] == order_id])
    return array_response([to_json(s) for s in items])


@app.route("/shipments/<shipment_id>/advance", methods=["POST"])
def advance_shipment(shipment_id):
    uid, role = require_auth()
    require_role(role, {"StudioOperator"})
    body = get_body()
    require_fields(body, ["to_status"])
    require_enum(body["to_status"], SHIPMENT_ADVANCE_ENUM, "to_status")
    shipment = get_or_404(db.shipments, shipment_id, "shipment")
    to_status = body["to_status"]
    cur = shipment["status"]

    legal = {
        "IN_TRANSIT": cur == "LABEL_CREATED",
        "DELIVERED": cur == "IN_TRANSIT",
        "RETURNED": cur == "IN_TRANSIT",
    }
    if not legal[to_status]:
        err("ERR_INVALID_STATE", 409, "Illegal shipment transition.")

    shipment["status"] = to_status
    if to_status == "DELIVERED":
        now = db.clock
        shipment["delivered_at"] = now
        touch(shipment)
        order = db.orders[shipment["order_id"]]
        if order["status"] == "MAILED":
            order["status"] = "DELIVERED"
            order["delivered_at"] = now
            touch(order)
    else:
        touch(shipment)
    return object_response(to_json(shipment))


@app.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    uid, role = require_auth()
    require_role(role, {"AccountHolder", "StudioOperator"})
    order = get_or_404(db.orders, order_id, "order")
    check_owner(role, uid, order["account_id"])

    cancellable = {"DRAFT", "PENDING_PROOF", "PROOF_APPROVED", "SCHEDULED", "IN_PRODUCTION"}
    if order["status"] not in cancellable:
        err("ERR_INVALID_STATE", 409, "Order cannot be cancelled from its current state.")

    order["status"] = "CANCELLED"
    touch(order)

    # refund credit if held/settled
    if order["credit_status"] in ("HELD", "SETTLED"):
        order["credit_status"] = "REFUNDED"
        add_credit_txn(order["account_id"], 1, "ORDER_REFUND")
        touch(db.accounts[order["account_id"]])

    # release reserved artist assignment
    assignment = order_reserved_assignment(order_id)
    if assignment is not None:
        assignment["status"] = "RELEASED"
        touch(assignment)
        recompute_artist_count(db.artists[assignment["artist_id"]])

    # void open proof
    proof = order_proof(order_id)
    if proof is not None and proof["status"] in ("PENDING", "CHANGES_REQUESTED"):
        proof["status"] = "VOIDED"
        touch(proof)

    return object_response(to_json(order))


# =====================================================================
# Clock & Scheduler
# =====================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    db.clock = parse_dt_field(body["to_iso8601"], "to_iso8601")
    return object_response({"current_utc": fmt_dt(db.clock)})


def auto_create_and_submit(imp):
    contact = db.contacts[imp["contact_id"]]
    account_id = contact["account_id"]
    order = build_order(
        account_id, imp["contact_id"], imp["default_card_id"],
        message_text="", scheduled_send_at=imp["event_date"],
        font_style="SCRIPT", gift_item_id=None, gift_quantity=0,
        important_date_id=imp["id"],
    )
    # auto-submit: hold one credit, create proof
    order["status"] = "PENDING_PROOF"
    order["credit_status"] = "HELD"
    add_credit_txn(account_id, -1, "ORDER_HOLD")
    touch(db.accounts[account_id])
    touch(order)
    proof = base_entity({
        "order_id": order["id"],
        "status": "PENDING",
        "proof_image_ref": "proofimg_" + uuid.uuid4().hex,
        "revision_count": 0,
        "reviewer_notes": None,
    })
    db.proofs[proof["id"]] = proof
    # advance recurrence by one year
    imp["event_date"] = add_years(imp["event_date"], 1)
    imp["next_trigger_at"] = imp["event_date"] - timedelta(days=imp["lead_days"])
    touch(imp)
    return order["id"]


@app.route("/_scheduler/run", methods=["POST"])
def scheduler_run():
    uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})

    fired_ids = []
    created_order_ids = []

    # Sweep 1: due reminders
    for imp in sort_seq(list(db.important_dates.values())):
        if imp["status"] != "ACTIVE":
            continue
        if not imp["auto_send"]:
            continue
        if imp["next_trigger_at"] > db.clock:
            continue
        contact = db.contacts.get(imp["contact_id"])
        if contact is None or contact["address_status"] != "VERIFIED":
            continue
        account = db.accounts.get(contact["account_id"])
        if account is None or account["card_credit_balance"] < 1:
            continue
        if not imp.get("default_card_id") or imp["default_card_id"] not in db.cards:
            continue
        order_id = auto_create_and_submit(imp)
        fired_ids.append(imp["id"])
        created_order_ids.append(order_id)

    # Sweep 2: subscription renewals
    renewed_ids = []
    for sub in sort_seq(list(db.subscriptions.values())):
        if sub["status"] != "ACTIVE":
            continue
        if sub["next_renewal_at"] > db.clock:
            continue
        account = db.accounts[sub["account_id"]]
        add_credit_txn(sub["account_id"], sub["monthly_card_credits"], "SUBSCRIPTION_GRANT")
        touch(account)
        sub["current_period_start"] = sub["current_period_start"] + timedelta(days=PERIOD_DAYS)
        sub["current_period_end"] = sub["current_period_start"] + timedelta(days=PERIOD_DAYS)
        sub["next_renewal_at"] = sub["current_period_end"]
        touch(sub)
        renewed_ids.append(sub["id"])

    data = {
        "fired_important_date_ids": fired_ids,
        "created_order_ids": created_order_ids,
        "renewed_subscription_ids": renewed_ids,
    }
    return object_response(data)


# =====================================================================
# Bootstrap
# =====================================================================
db = Store()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
