"""
Gift-Card Program & Distribution Platform (B2B) — reference implementation.

In-memory only (dicts keyed by id). No seeding at startup. The store starts
empty on every boot; tests build all preconditions via the declared API surface.
"""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
KNOWN_ROLES = {
    "PlatformAdmin", "MerchantAdmin", "POSTerminal",
    "FraudAnalyst", "SettlementOfficer", "Any",
}

BREAKAGE_RATE_BPS = 1000

TIER1_MAX_CENTS = 1_000_000
TIER1_RATE_BPS = 300
TIER2_MAX_CENTS = 5_000_000
TIER2_RATE_BPS = 250
TIER3_RATE_BPS = 200
MIN_INTERCHANGE_CENTS = 2500

DORMANCY_DAYS = 365
DORMANCY_FEE_CENTS = 200

CAMPAIGN_GAP_DAYS = 7

DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

# =============================================================================
# In-memory store (empty at boot — NEVER seeded)
# =============================================================================
db = {
    "merchants": {},
    "programs": {},
    "campaigns": {},
    "batches": {},
    "cards": {},
    "ledger": {},          # id -> entry
    "holds": {},
    "vrules": {},
    "sbatches": {},
    "ereports": {},
}
_state = {"clock": DEFAULT_CLOCK, "seq": 0, "card_no": 0}


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def now():
    return _state["clock"]


def new_id():
    return str(uuid.uuid4())


def new_card_number():
    _state["card_no"] += 1
    return "GC" + str(1_000_000_000 + _state["card_no"])


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# =============================================================================
# Time helpers
# =============================================================================
def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime: %r" % s)


def add_months(dt, months):
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    # clamp day to last valid day of target month
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    last_day = (nxt - timedelta(days=1)).day
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def rhu(numerator, denominator):
    """round-half-up integer division numerator/denominator."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# Response envelope
# =============================================================================
def meta_base(extra=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": iso(now())}
    if extra:
        m.update(extra)
    return m


def ok(data, response_type="object", code=200, pagination=None):
    body = {
        "meta": meta_base(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"},
    }
    return jsonify(body), 404


# =============================================================================
# Auth / RBAC
# =============================================================================
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_MISSING_USER_CONTEXT", 400,
                       "missing or unknown user context")
    return uid, role


def auth(allowed_roles):
    uid, role = require_auth()
    if "Any" not in allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                       "role %s not permitted" % role)
    return uid, role


# =============================================================================
# Body / query helpers
# =============================================================================
def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def pos_int(v):
    return is_int(v) and v > 0


def nonneg_int(v):
    return is_int(v) and v >= 0


def require_positive(v, field):
    if not pos_int(v):
        raise ApiError("ERR_VALIDATION", 400, "%s must be a positive integer" % field)
    return v


def paginate(items):
    """items is a pre-sorted list; returns (page, pagination_meta)."""
    def to_int(name, default):
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    limit = to_int("limit", 10)
    offset = to_int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sorted_by_created(values):
    return sorted(values, key=lambda e: (e["created_at"], e["_seq"]))


# =============================================================================
# Common record helpers
# =============================================================================
def make_common():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] += 1


def common_out(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


# =============================================================================
# Ledger / balance
# =============================================================================
def post_ledger(card_id, entry_type, amount_cents, memo="", settlement_batch_id=None):
    ts = now()
    e = {
        "id": new_id(),
        "gift_card_id": card_id,
        "settlement_batch_id": settlement_batch_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "status": "POSTED",
        "memo": memo,
        "created_at": ts,
        "_seq": next_seq(),
    }
    db["ledger"][e["id"]] = e
    return e


def card_entries(card_id):
    return [e for e in db["ledger"].values() if e["gift_card_id"] == card_id]


def balance(card_id):
    return sum(e["amount_cents"] for e in db["ledger"].values()
               if e["gift_card_id"] == card_id and e["status"] == "POSTED")


def card_merchant_id(card):
    prog = db["programs"].get(card["card_program_id"])
    return prog["merchant_id"] if prog else None


def merchant_cards(merchant_id):
    result = []
    for c in db["cards"].values():
        if card_merchant_id(c) == merchant_id:
            result.append(c)
    return result


# =============================================================================
# Serialization
# =============================================================================
def ser_merchant(m):
    out = common_out(m)
    out.update({
        "legal_name": m["legal_name"],
        "settlement_currency": m["settlement_currency"],
        "status": m["status"],
        "unsettled_redemptions_cents": merchant_unsettled(m["id"]),
        "lifetime_net_payout_cents": merchant_lifetime(m["id"]),
    })
    return out


def merchant_unsettled(merchant_id):
    total = 0
    for c in merchant_cards(merchant_id):
        for e in db["ledger"].values():
            if (e["gift_card_id"] == c["id"] and e["entry_type"] == "REDEMPTION"
                    and e["status"] == "POSTED" and e["settlement_batch_id"] is None):
                total += -e["amount_cents"]
    return total


def merchant_lifetime(merchant_id):
    total = 0
    for b in db["sbatches"].values():
        if b["merchant_id"] == merchant_id and b["status"] == "FINALIZED":
            total += b["net_payout_cents"]
    return total


def ser_program(p):
    out = common_out(p)
    out.update({
        "merchant_id": p["merchant_id"],
        "name": p["name"],
        "currency": p["currency"],
        "breakage_method": p["breakage_method"],
        "expiry_months": p["expiry_months"],
        "max_balance_cents": p["max_balance_cents"],
        "min_load_cents": p["min_load_cents"],
        "status": p["status"],
        "outstanding_balance_cents": program_outstanding(p["id"]),
        "breakage_recognized_cents": program_breakage(p),
    })
    return out


def program_outstanding(program_id):
    total = 0
    for c in db["cards"].values():
        if c["card_program_id"] == program_id and c["status"] == "ACTIVE":
            total += balance(c["id"])
    return total


def program_breakage(p):
    if p["breakage_method"] == "ESTIMATED":
        return p["estimated_breakage_cents"]
    # REMITTANCE: sum of magnitudes of BREAKAGE ledger entries on program cards
    total = 0
    for c in db["cards"].values():
        if c["card_program_id"] == p["id"]:
            for e in db["ledger"].values():
                if e["gift_card_id"] == c["id"] and e["entry_type"] == "BREAKAGE":
                    total += -e["amount_cents"]
    return total


def campaign_status(c):
    t = now()
    if t < c["starts_at"]:
        return "SCHEDULED"
    if c["starts_at"] <= t <= c["ends_at"]:
        return "RUNNING"
    return "ENDED"


def ser_campaign(c):
    out = common_out(c)
    out.update({
        "card_program_id": c["card_program_id"],
        "name": c["name"],
        "bonus_bps": c["bonus_bps"],
        "starts_at": iso(c["starts_at"]),
        "ends_at": iso(c["ends_at"]),
        "status": campaign_status(c),
    })
    return out


def ser_batch(b):
    out = common_out(b)
    out.update({
        "card_program_id": b["card_program_id"],
        "channel": b["channel"],
        "card_count": b["card_count"],
        "unit_load_cents": b["unit_load_cents"],
        "purpose": b["purpose"],
        "status": b["status"],
        "committed_at": iso(b["committed_at"]),
    })
    return out


def card_dormant(c):
    if c["status"] != "ACTIVE" or c["last_activity_at"] is None:
        return False
    return (now() - c["last_activity_at"]) >= timedelta(days=DORMANCY_DAYS)


def ser_card(c):
    out = common_out(c)
    out.update({
        "card_program_id": c["card_program_id"],
        "card_batch_id": c["card_batch_id"],
        "incentive_campaign_id": c["incentive_campaign_id"],
        "card_number": c["card_number"],
        "channel": c["channel"],
        "status": c["status"],
        "balance_cents": balance(c["id"]),
        "initial_load_cents": c["initial_load_cents"],
        "activated_at": iso(c["activated_at"]),
        "expires_at": iso(c["expires_at"]),
        "last_activity_at": iso(c["last_activity_at"]),
        "dormant": card_dormant(c),
    })
    return out


def ser_ledger(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "gift_card_id": e["gift_card_id"],
        "settlement_batch_id": e["settlement_batch_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
        "memo": e["memo"],
    }


def hold_reversed_count(h):
    return h.get("reversed_redemption_count", 0)


def ser_hold(h):
    out = common_out(h)
    out.update({
        "gift_card_id": h["gift_card_id"],
        "reason": h["reason"],
        "opened_by_user_id": h["opened_by_user_id"],
        "resolved_by_user_id": h["resolved_by_user_id"],
        "status": h["status"],
        "reversed_redemption_count": hold_reversed_count(h),
    })
    return out


def ser_vrule(v):
    out = common_out(v)
    out.update({
        "card_program_id": v["card_program_id"],
        "window_hours": v["window_hours"],
        "max_count": v["max_count"],
        "max_amount_cents": v["max_amount_cents"],
        "enabled": v["enabled"],
    })
    return out


def ser_sbatch(b):
    out = common_out(b)
    out.update({
        "merchant_id": b["merchant_id"],
        "period_start": iso(b["period_start"]),
        "period_end": iso(b["period_end"]),
        "opened_by_user_id": b["opened_by_user_id"],
        "finalized_by_user_id": b["finalized_by_user_id"],
        "status": b["status"],
        "gross_redemptions_cents": b["gross_redemptions_cents"],
        "interchange_fee_cents": b["interchange_fee_cents"],
        "net_payout_cents": b["net_payout_cents"],
        "provisional_net_payout_cents": b["provisional_net_payout_cents"],
    })
    return out


def ser_ereport(r):
    out = common_out(r)
    out.update({
        "merchant_id": r["merchant_id"],
        "jurisdiction": r["jurisdiction"],
        "period_start": iso(r["period_start"]),
        "period_end": iso(r["period_end"]),
        "status": r["status"],
        "escheat_total_cents": r["escheat_total_cents"],
        "card_count": r["card_count"],
    })
    return out


# =============================================================================
# Calculations
# =============================================================================
def interchange_fee(gross):
    if gross == 0:
        return 0
    if gross <= TIER1_MAX_CENTS:
        rate = TIER1_RATE_BPS
    elif gross <= TIER2_MAX_CENTS:
        rate = TIER2_RATE_BPS
    else:
        rate = TIER3_RATE_BPS
    raw = rhu(gross * rate, 10000)
    return max(MIN_INTERCHANGE_CENTS, raw)


def batch_swept_posted(batch_id):
    return [e for e in db["ledger"].values()
            if e["settlement_batch_id"] == batch_id
            and e["entry_type"] == "REDEMPTION" and e["status"] == "POSTED"]


def recompute_batch_final(batch):
    gross = sum(-e["amount_cents"] for e in batch_swept_posted(batch["id"]))
    fee = interchange_fee(gross)
    batch["gross_redemptions_cents"] = gross
    batch["interchange_fee_cents"] = fee
    batch["net_payout_cents"] = gross - fee


# =============================================================================
# Ownership
# =============================================================================
def check_program_owner(program, uid, role):
    if role == "MerchantAdmin" and program["merchant_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")


# =============================================================================
# Existence helpers
# =============================================================================
def get_or_404(collection, rid):
    e = db[collection].get(rid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    return e


# =============================================================================
# Logical clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["PlatformAdmin"])
    b = body()
    if "to_iso8601" not in b:
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 required")
    _state["clock"] = parse_dt(b["to_iso8601"])
    return ok({"current_utc": iso(now())}, "object", 200)


# =============================================================================
# Merchant
# =============================================================================
@app.route("/merchants", methods=["POST"])
def create_merchant():
    auth(["PlatformAdmin"])
    b = body()
    legal_name = b.get("legal_name")
    if not isinstance(legal_name, str) or legal_name == "":
        raise ApiError("ERR_VALIDATION", 400, "legal_name required")
    currency = b.get("settlement_currency", "USD")
    if not isinstance(currency, str) or currency == "":
        raise ApiError("ERR_VALIDATION", 400, "invalid settlement_currency")
    m = make_common()
    m.update({
        "legal_name": legal_name,
        "settlement_currency": currency,
        "status": "PENDING",
    })
    db["merchants"][m["id"]] = m
    return ok(ser_merchant(m), "object", 201)


@app.route("/merchants/<merchant_id>", methods=["GET"])
def get_merchant(merchant_id):
    auth(["Any"])
    m = get_or_404("merchants", merchant_id)
    return ok(ser_merchant(m), "object", 200)


def _merchant_transition(merchant_id, allowed_from, to_status, extra_check=None):
    auth(["PlatformAdmin"])
    m = get_or_404("merchants", merchant_id)
    if m["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    if extra_check:
        extra_check(m)
    m["status"] = to_status
    touch(m)
    return ok(ser_merchant(m), "object", 200)


@app.route("/merchants/<merchant_id>/activate", methods=["POST"])
def activate_merchant(merchant_id):
    return _merchant_transition(merchant_id, {"PENDING"}, "ACTIVE")


@app.route("/merchants/<merchant_id>/suspend", methods=["POST"])
def suspend_merchant(merchant_id):
    return _merchant_transition(merchant_id, {"ACTIVE"}, "SUSPENDED")


@app.route("/merchants/<merchant_id>/reactivate", methods=["POST"])
def reactivate_merchant(merchant_id):
    return _merchant_transition(merchant_id, {"SUSPENDED"}, "ACTIVE")


@app.route("/merchants/<merchant_id>/close", methods=["POST"])
def close_merchant(merchant_id):
    def no_open_batch(m):
        for b in db["sbatches"].values():
            if b["merchant_id"] == m["id"] and b["status"] == "OPEN":
                raise ApiError("ERR_INVALID_STATE", 409, "open settlement batch exists")
    return _merchant_transition(merchant_id, {"ACTIVE", "SUSPENDED"}, "CLOSED",
                                extra_check=no_open_batch)


# =============================================================================
# CardProgram
# =============================================================================
@app.route("/card-programs", methods=["POST"])
def create_program():
    uid, role = auth(["MerchantAdmin"])
    b = body()
    merchant_id = b.get("merchant_id")
    # ownership (priority 3) — pure comparison, before existence
    if isinstance(merchant_id, str) and merchant_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    # existence (priority 4)
    if isinstance(merchant_id, str):
        get_or_404("merchants", merchant_id)
    # validation (priority 5)
    if not isinstance(merchant_id, str):
        raise ApiError("ERR_VALIDATION", 400, "merchant_id required")
    name = b.get("name")
    if not isinstance(name, str) or name == "":
        raise ApiError("ERR_VALIDATION", 400, "name required")
    currency = b.get("currency", "USD")
    if not isinstance(currency, str) or currency == "":
        raise ApiError("ERR_VALIDATION", 400, "invalid currency")
    breakage_method = b.get("breakage_method", "REMITTANCE")
    if breakage_method not in ("ESTIMATED", "REMITTANCE"):
        raise ApiError("ERR_VALIDATION", 400, "invalid breakage_method")
    expiry_months = b.get("expiry_months", 12)
    if not is_int(expiry_months) or expiry_months < 1:
        raise ApiError("ERR_VALIDATION", 400, "invalid expiry_months")
    max_balance_cents = b.get("max_balance_cents", 100000)
    if not pos_int(max_balance_cents):
        raise ApiError("ERR_VALIDATION", 400, "invalid max_balance_cents")
    min_load_cents = b.get("min_load_cents", 500)
    if not pos_int(min_load_cents):
        raise ApiError("ERR_VALIDATION", 400, "invalid min_load_cents")
    p = make_common()
    p.update({
        "merchant_id": merchant_id,
        "name": name,
        "currency": currency,
        "breakage_method": breakage_method,
        "expiry_months": expiry_months,
        "max_balance_cents": max_balance_cents,
        "min_load_cents": min_load_cents,
        "status": "DRAFT",
        "estimated_breakage_cents": 0,
    })
    db["programs"][p["id"]] = p
    return ok(ser_program(p), "object", 201)


@app.route("/card-programs/<program_id>", methods=["GET"])
def get_program(program_id):
    auth(["Any"])
    p = get_or_404("programs", program_id)
    return ok(ser_program(p), "object", 200)


@app.route("/card-programs", methods=["GET"])
def list_programs():
    auth(["Any"])
    items = list(db["programs"].values())
    mid = request.args.get("merchant_id")
    st = request.args.get("status")
    if mid is not None:
        items = [p for p in items if p["merchant_id"] == mid]
    if st is not None:
        items = [p for p in items if p["status"] == st]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([ser_program(p) for p in page], "array", 200, meta)


def _program_transition(program_id, allowed_from, to_status, require_merchant_active=False,
                        side_effect=None):
    uid, role = auth(["MerchantAdmin"])
    p = get_or_404("programs", program_id)
    check_program_owner(p, uid, role)
    if p["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    if require_merchant_active:
        m = db["merchants"].get(p["merchant_id"])
        if not m or m["status"] != "ACTIVE":
            raise ApiError("ERR_MERCHANT_NOT_ACTIVE", 409, "merchant not active")
    p["status"] = to_status
    touch(p)
    if side_effect:
        side_effect(p)
    return ok(ser_program(p), "object", 200)


@app.route("/card-programs/<program_id>/activate", methods=["POST"])
def activate_program(program_id):
    return _program_transition(program_id, {"DRAFT"}, "ACTIVE", require_merchant_active=True)


@app.route("/card-programs/<program_id>/pause", methods=["POST"])
def pause_program(program_id):
    return _program_transition(program_id, {"ACTIVE"}, "PAUSED")


@app.route("/card-programs/<program_id>/resume", methods=["POST"])
def resume_program(program_id):
    return _program_transition(program_id, {"PAUSED"}, "ACTIVE")


@app.route("/card-programs/<program_id>/retire", methods=["POST"])
def retire_program(program_id):
    return _program_transition(program_id, {"ACTIVE", "PAUSED"}, "RETIRED")


@app.route("/card-programs/<program_id>/run-maintenance", methods=["POST"])
def run_maintenance(program_id):
    uid, role = auth(["PlatformAdmin", "MerchantAdmin"])
    p = get_or_404("programs", program_id)
    check_program_owner(p, uid, role)
    t = now()
    prog_cards = [c for c in db["cards"].values() if c["card_program_id"] == program_id]
    # 1) Expiry
    for c in prog_cards:
        if c["status"] == "ACTIVE" and c["expires_at"] is not None and t >= c["expires_at"]:
            c["status"] = "EXPIRED"
            if p["breakage_method"] == "REMITTANCE":
                bal = balance(c["id"])
                if bal > 0:
                    post_ledger(c["id"], "BREAKAGE", -bal, "expiry breakage forfeit")
            touch(c)
    # 2) Dormancy
    for c in prog_cards:
        if c["status"] == "ACTIVE" and c["last_activity_at"] is not None:
            if (t - c["last_activity_at"]) >= timedelta(days=DORMANCY_DAYS):
                bal = balance(c["id"])
                if bal > 0:
                    fee = min(DORMANCY_FEE_CENTS, bal)
                    post_ledger(c["id"], "DORMANCY_FEE", -fee, "dormancy fee")
                    touch(c)
    # 3) Estimated breakage recognition
    if p["breakage_method"] == "ESTIMATED":
        total = 0
        for c in prog_cards:
            if c["status"] == "ACTIVE":
                total += rhu(balance(c["id"]) * BREAKAGE_RATE_BPS, 10000)
        p["estimated_breakage_cents"] = total
    return ok(ser_program(p), "object", 200)


# =============================================================================
# IncentiveCampaign
# =============================================================================
@app.route("/incentive-campaigns", methods=["POST"])
def create_campaign():
    uid, role = auth(["MerchantAdmin"])
    b = body()
    program_id = b.get("card_program_id")
    prog = db["programs"].get(program_id) if isinstance(program_id, str) else None
    # ownership (3)
    if prog is not None:
        check_program_owner(prog, uid, role)
    # existence (4)
    if isinstance(program_id, str) and prog is None:
        raise ApiError("ERR_NOT_FOUND", 404, "card program not found")
    # validation (5)
    if not isinstance(program_id, str):
        raise ApiError("ERR_VALIDATION", 400, "card_program_id required")
    name = b.get("name")
    if not isinstance(name, str) or name == "":
        raise ApiError("ERR_VALIDATION", 400, "name required")
    bonus_bps = b.get("bonus_bps")
    if not nonneg_int(bonus_bps):
        raise ApiError("ERR_VALIDATION", 400, "invalid bonus_bps")
    if "starts_at" not in b or "ends_at" not in b:
        raise ApiError("ERR_VALIDATION", 400, "starts_at and ends_at required")
    starts_at = parse_dt(b["starts_at"])
    ends_at = parse_dt(b["ends_at"])
    if ends_at < starts_at:
        raise ApiError("ERR_VALIDATION", 400, "ends_at before starts_at")
    # window buffer (priority 11)
    gap = timedelta(days=CAMPAIGN_GAP_DAYS)
    for other in db["campaigns"].values():
        if other["card_program_id"] != program_id:
            continue
        # required separation of at least CAMPAIGN_GAP_DAYS between closed windows
        if ends_at < other["starts_at"]:
            sep = other["starts_at"] - ends_at
        elif other["ends_at"] < starts_at:
            sep = starts_at - other["ends_at"]
        else:
            sep = timedelta(0)  # overlap
        if sep < gap:
            raise ApiError("ERR_CAMPAIGN_WINDOW_OVERLAP", 409, "campaign window buffer violated")
    c = make_common()
    c.update({
        "card_program_id": program_id,
        "name": name,
        "bonus_bps": bonus_bps,
        "starts_at": starts_at,
        "ends_at": ends_at,
    })
    db["campaigns"][c["id"]] = c
    return ok(ser_campaign(c), "object", 201)


@app.route("/incentive-campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    auth(["Any"])
    c = get_or_404("campaigns", campaign_id)
    return ok(ser_campaign(c), "object", 200)


@app.route("/incentive-campaigns", methods=["GET"])
def list_campaigns():
    auth(["Any"])
    items = list(db["campaigns"].values())
    pid = request.args.get("card_program_id")
    st = request.args.get("status")
    if pid is not None:
        items = [c for c in items if c["card_program_id"] == pid]
    if st is not None:
        items = [c for c in items if campaign_status(c) == st]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([ser_campaign(c) for c in page], "array", 200, meta)


# =============================================================================
# CardBatch
# =============================================================================
@app.route("/card-batches", methods=["POST"])
def create_batch():
    uid, role = auth(["MerchantAdmin"])
    b = body()
    program_id = b.get("card_program_id")
    prog = db["programs"].get(program_id) if isinstance(program_id, str) else None
    if prog is not None:
        check_program_owner(prog, uid, role)
    if isinstance(program_id, str) and prog is None:
        raise ApiError("ERR_NOT_FOUND", 404, "card program not found")
    if not isinstance(program_id, str):
        raise ApiError("ERR_VALIDATION", 400, "card_program_id required")
    channel = b.get("channel")
    if channel not in ("DIGITAL", "PHYSICAL"):
        raise ApiError("ERR_VALIDATION", 400, "invalid channel")
    card_count = b.get("card_count")
    if not is_int(card_count) or card_count < 1:
        raise ApiError("ERR_VALIDATION", 400, "invalid card_count")
    unit_load_cents = b.get("unit_load_cents")
    if not pos_int(unit_load_cents):
        raise ApiError("ERR_VALIDATION", 400, "invalid unit_load_cents")
    purpose = b.get("purpose", "RETAIL")
    if purpose not in ("RETAIL", "B2B_BULK", "INCENTIVE"):
        raise ApiError("ERR_VALIDATION", 400, "invalid purpose")
    bt = make_common()
    bt.update({
        "card_program_id": program_id,
        "channel": channel,
        "card_count": card_count,
        "unit_load_cents": unit_load_cents,
        "purpose": purpose,
        "status": "DRAFT",
        "committed_at": None,
    })
    db["batches"][bt["id"]] = bt
    return ok(ser_batch(bt), "object", 201)


@app.route("/card-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    auth(["Any"])
    bt = get_or_404("batches", batch_id)
    return ok(ser_batch(bt), "object", 200)


@app.route("/card-batches", methods=["GET"])
def list_batches():
    auth(["Any"])
    items = list(db["batches"].values())
    pid = request.args.get("card_program_id")
    st = request.args.get("status")
    if pid is not None:
        items = [x for x in items if x["card_program_id"] == pid]
    if st is not None:
        items = [x for x in items if x["status"] == st]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([ser_batch(x) for x in page], "array", 200, meta)


@app.route("/card-batches/<batch_id>/commit", methods=["POST"])
def commit_batch(batch_id):
    uid, role = auth(["MerchantAdmin"])
    bt = get_or_404("batches", batch_id)
    prog = db["programs"].get(bt["card_program_id"])
    if prog is not None:
        check_program_owner(prog, uid, role)
    if bt["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    if not prog or prog["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409, "program not active")
    for _ in range(bt["card_count"]):
        c = make_common()
        c.update({
            "card_program_id": bt["card_program_id"],
            "card_batch_id": bt["id"],
            "incentive_campaign_id": None,
            "card_number": new_card_number(),
            "channel": bt["channel"],
            "status": "INACTIVE",
            "initial_load_cents": bt["unit_load_cents"],
            "activated_at": None,
            "expires_at": None,
            "last_activity_at": None,
        })
        db["cards"][c["id"]] = c
    bt["status"] = "COMMITTED"
    bt["committed_at"] = now()
    touch(bt)
    return ok(ser_batch(bt), "object", 200)


@app.route("/card-batches/<batch_id>/cancel", methods=["POST"])
def cancel_batch(batch_id):
    uid, role = auth(["MerchantAdmin"])
    bt = get_or_404("batches", batch_id)
    prog = db["programs"].get(bt["card_program_id"])
    if prog is not None:
        check_program_owner(prog, uid, role)
    if bt["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    bt["status"] = "CANCELLED"
    touch(bt)
    return ok(ser_batch(bt), "object", 200)


# =============================================================================
# GiftCard
# =============================================================================
@app.route("/gift-cards/<card_id>", methods=["GET"])
def get_card(card_id):
    auth(["Any"])
    c = get_or_404("cards", card_id)
    return ok(ser_card(c), "object", 200)


@app.route("/gift-cards/<card_id>/balance", methods=["GET"])
def card_balance_api(card_id):
    auth(["Any"])
    c = get_or_404("cards", card_id)
    prog = db["programs"].get(c["card_program_id"])
    currency = prog["currency"] if prog else None
    data = {
        "card_number": c["card_number"],
        "status": c["status"],
        "balance_cents": balance(c["id"]),
        "currency": currency,
    }
    return ok(data, "object", 200)


@app.route("/gift-cards", methods=["GET"])
def list_cards():
    auth(["Any"])
    items = list(db["cards"].values())
    for key in ("card_program_id", "card_batch_id", "incentive_campaign_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([ser_card(c) for c in page], "array", 200, meta)


def card_owner_check(card, uid, role):
    if role == "MerchantAdmin":
        prog = db["programs"].get(card["card_program_id"])
        if not prog or prog["merchant_id"] != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")


@app.route("/gift-cards/<card_id>/activate", methods=["POST"])
def activate_card(card_id):
    uid, role = auth(["POSTerminal", "MerchantAdmin"])
    c = get_or_404("cards", card_id)
    card_owner_check(c, uid, role)
    if c["status"] != "INACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    prog = db["programs"].get(c["card_program_id"])
    if not prog or prog["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409, "program not active")
    t = now()
    post_ledger(c["id"], "ACTIVATION_LOAD", c["initial_load_cents"], "activation load")
    c["status"] = "ACTIVE"
    c["activated_at"] = t
    c["expires_at"] = add_months(t, prog["expiry_months"])
    c["last_activity_at"] = t
    touch(c)
    return ok(ser_card(c), "object", 200)


@app.route("/gift-cards/<card_id>/redeem", methods=["POST"])
def redeem_card(card_id):
    uid, role = auth(["POSTerminal"])
    c = get_or_404("cards", card_id)
    b = body()
    amount = b.get("amount_cents")
    require_positive(amount, "amount_cents")
    # card must be ACTIVE
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CARD_NOT_ACTIVE", 409, "card not active")
    # velocity check
    _velocity_check(c, amount)
    # sufficient balance
    if amount > balance(c["id"]):
        raise ApiError("ERR_INSUFFICIENT_BALANCE", 409, "insufficient balance")
    post_ledger(c["id"], "REDEMPTION", -amount, "redemption")
    c["last_activity_at"] = now()
    if balance(c["id"]) == 0:
        c["status"] = "CLOSED"
    touch(c)
    return ok(ser_card(c), "object", 200)


def _velocity_check(card, amount):
    rule = None
    for v in db["vrules"].values():
        if v["card_program_id"] == card["card_program_id"] and v["enabled"]:
            rule = v
            break
    if rule is None:
        return
    window_start = now() - timedelta(hours=rule["window_hours"])
    prior = [e for e in db["ledger"].values()
             if e["gift_card_id"] == card["id"] and e["entry_type"] == "REDEMPTION"
             and e["status"] == "POSTED" and e["created_at"] >= window_start]
    count_incl = len(prior) + 1
    amount_incl = sum(-e["amount_cents"] for e in prior) + amount
    if count_incl > rule["max_count"] or amount_incl > rule["max_amount_cents"]:
        raise ApiError("ERR_VELOCITY_EXCEEDED", 409, "velocity limit exceeded")


@app.route("/gift-cards/<card_id>/reload", methods=["POST"])
def reload_card(card_id):
    uid, role = auth(["POSTerminal", "MerchantAdmin"])
    c = get_or_404("cards", card_id)
    card_owner_check(c, uid, role)
    b = body()
    amount = b.get("amount_cents")
    require_positive(amount, "amount_cents")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CARD_NOT_ACTIVE", 409, "card not active")
    prog = db["programs"].get(c["card_program_id"])
    if not prog or prog["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409, "program not active")
    if amount < prog["min_load_cents"]:
        raise ApiError("ERR_BELOW_MIN_LOAD", 422, "below minimum load")
    # incentive bonus (from RUNNING campaign)
    campaign = _running_campaign(prog["id"])
    bonus = 0
    if campaign is not None:
        bonus = rhu(amount * campaign["bonus_bps"], 10000)
    projected = balance(c["id"]) + amount + bonus
    if projected > prog["max_balance_cents"]:
        raise ApiError("ERR_MAX_BALANCE_EXCEEDED", 409, "max balance exceeded")
    post_ledger(c["id"], "RELOAD", amount, "reload")
    if campaign is not None and bonus > 0:
        post_ledger(c["id"], "INCENTIVE_BONUS", bonus, "incentive bonus")
        c["incentive_campaign_id"] = campaign["id"]
    c["last_activity_at"] = now()
    touch(c)
    return ok(ser_card(c), "object", 200)


def _running_campaign(program_id):
    t = now()
    for cmp in db["campaigns"].values():
        if cmp["card_program_id"] == program_id and cmp["starts_at"] <= t <= cmp["ends_at"]:
            return cmp
    return None


# =============================================================================
# LedgerEntry
# =============================================================================
@app.route("/ledger-entries/<entry_id>", methods=["GET"])
def get_ledger(entry_id):
    auth(["Any"])
    e = get_or_404("ledger", entry_id)
    return ok(ser_ledger(e), "object", 200)


@app.route("/ledger-entries", methods=["GET"])
def list_ledger():
    auth(["Any"])
    items = list(db["ledger"].values())
    for key in ("gift_card_id", "settlement_batch_id", "entry_type", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([ser_ledger(e) for e in page], "array", 200, meta)


# =============================================================================
# FraudHold
# =============================================================================
@app.route("/fraud-holds", methods=["POST"])
def open_hold():
    uid, role = auth(["FraudAnalyst"])
    b = body()
    card_id = b.get("gift_card_id")
    if isinstance(card_id, str):
        get_or_404("cards", card_id)
    if not isinstance(card_id, str):
        raise ApiError("ERR_VALIDATION", 400, "gift_card_id required")
    reason = b.get("reason")
    if reason not in ("VELOCITY", "MANUAL", "CHARGEBACK"):
        raise ApiError("ERR_VALIDATION", 400, "invalid reason")
    c = db["cards"][card_id]
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "card not active")
    h = make_common()
    h.update({
        "gift_card_id": card_id,
        "reason": reason,
        "opened_by_user_id": uid,
        "resolved_by_user_id": None,
        "status": "OPEN",
        "reversed_redemption_count": 0,
    })
    db["holds"][h["id"]] = h
    c["status"] = "SUSPENDED"
    touch(c)
    return ok(ser_hold(h), "object", 201)


@app.route("/fraud-holds/<hold_id>", methods=["GET"])
def get_hold(hold_id):
    auth(["Any"])
    h = get_or_404("holds", hold_id)
    return ok(ser_hold(h), "object", 200)


@app.route("/fraud-holds", methods=["GET"])
def list_holds():
    auth(["Any"])
    items = list(db["holds"].values())
    for key in ("gift_card_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [h for h in items if h[key] == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([ser_hold(h) for h in page], "array", 200, meta)


@app.route("/fraud-holds/<hold_id>/clear", methods=["POST"])
def clear_hold(hold_id):
    uid, role = auth(["FraudAnalyst"])
    h = get_or_404("holds", hold_id)
    if h["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    h["resolved_by_user_id"] = uid
    h["status"] = "CLEARED"
    touch(h)
    c = db["cards"].get(h["gift_card_id"])
    if c and c["status"] == "SUSPENDED":
        c["status"] = "ACTIVE"
        touch(c)
    return ok(ser_hold(h), "object", 200)


@app.route("/fraud-holds/<hold_id>/confirm", methods=["POST"])
def confirm_hold(hold_id):
    uid, role = auth(["FraudAnalyst"])
    h = get_or_404("holds", hold_id)
    if h["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    if uid == h["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "opener may not confirm")
    h["resolved_by_user_id"] = uid
    h["status"] = "CONFIRMED"
    card_id = h["gift_card_id"]
    reversed_count = 0
    affected_open_batches = set()
    for e in db["ledger"].values():
        if (e["gift_card_id"] == card_id and e["entry_type"] == "REDEMPTION"
                and e["status"] == "POSTED"):
            e["status"] = "REVERSED"
            reversed_count += 1
            sb_id = e["settlement_batch_id"]
            if sb_id is not None:
                sb = db["sbatches"].get(sb_id)
                if sb and sb["status"] == "OPEN":
                    affected_open_batches.add(sb_id)
    h["reversed_redemption_count"] = reversed_count
    # recompute affected OPEN settlement batches (final view over remaining POSTED)
    for sb_id in affected_open_batches:
        recompute_batch_final(db["sbatches"][sb_id])
        touch(db["sbatches"][sb_id])
    # card stays SUSPENDED; touch to reflect balance restoration
    c = db["cards"].get(card_id)
    if c:
        touch(c)
    return ok(ser_hold(h), "object", 200)


# =============================================================================
# VelocityRule
# =============================================================================
@app.route("/velocity-rules", methods=["POST"])
def create_vrule():
    uid, role = auth(["MerchantAdmin"])
    b = body()
    program_id = b.get("card_program_id")
    prog = db["programs"].get(program_id) if isinstance(program_id, str) else None
    if prog is not None:
        check_program_owner(prog, uid, role)
    if isinstance(program_id, str) and prog is None:
        raise ApiError("ERR_NOT_FOUND", 404, "card program not found")
    if not isinstance(program_id, str):
        raise ApiError("ERR_VALIDATION", 400, "card_program_id required")
    window_hours = b.get("window_hours", 24)
    if not is_int(window_hours) or window_hours < 1:
        raise ApiError("ERR_VALIDATION", 400, "invalid window_hours")
    max_count = b.get("max_count", 5)
    if not nonneg_int(max_count):
        raise ApiError("ERR_VALIDATION", 400, "invalid max_count")
    max_amount_cents = b.get("max_amount_cents", 50000)
    if not nonneg_int(max_amount_cents):
        raise ApiError("ERR_VALIDATION", 400, "invalid max_amount_cents")
    enabled = b.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ApiError("ERR_VALIDATION", 400, "invalid enabled")
    v = make_common()
    v.update({
        "card_program_id": program_id,
        "window_hours": window_hours,
        "max_count": max_count,
        "max_amount_cents": max_amount_cents,
        "enabled": enabled,
    })
    db["vrules"][v["id"]] = v
    return ok(ser_vrule(v), "object", 201)


@app.route("/velocity-rules/<rule_id>", methods=["GET"])
def get_vrule(rule_id):
    auth(["Any"])
    v = get_or_404("vrules", rule_id)
    return ok(ser_vrule(v), "object", 200)


@app.route("/velocity-rules", methods=["GET"])
def list_vrules():
    auth(["Any"])
    items = list(db["vrules"].values())
    pid = request.args.get("card_program_id")
    if pid is not None:
        items = [v for v in items if v["card_program_id"] == pid]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([ser_vrule(v) for v in page], "array", 200, meta)


# =============================================================================
# SettlementBatch
# =============================================================================
@app.route("/settlement-batches", methods=["POST"])
def open_settlement():
    uid, role = auth(["SettlementOfficer"])
    b = body()
    merchant_id = b.get("merchant_id")
    if isinstance(merchant_id, str):
        get_or_404("merchants", merchant_id)
    if not isinstance(merchant_id, str):
        raise ApiError("ERR_VALIDATION", 400, "merchant_id required")
    if "period_start" not in b or "period_end" not in b:
        raise ApiError("ERR_VALIDATION", 400, "period_start and period_end required")
    period_start = parse_dt(b["period_start"])
    period_end = parse_dt(b["period_end"])
    expected_version = b.get("expected_merchant_version")
    if not is_int(expected_version):
        raise ApiError("ERR_VALIDATION", 400, "expected_merchant_version required")
    if period_end <= period_start:
        raise ApiError("ERR_VALIDATION", 400, "period_end must be after period_start")
    m = db["merchants"][merchant_id]
    # overlap check (priority 10)
    for other in db["sbatches"].values():
        if other["merchant_id"] != merchant_id or other["status"] == "CANCELLED":
            continue
        if period_start < other["period_end"] and other["period_start"] < period_end:
            raise ApiError("ERR_SETTLEMENT_PERIOD_OVERLAP", 409, "settlement period overlap")
    # OCC (priority 18)
    if expected_version != m["version"]:
        raise ApiError("ERR_STALE_MERCHANT_VERSION", 412, "stale merchant version")
    sb = make_common()
    sb.update({
        "merchant_id": merchant_id,
        "period_start": period_start,
        "period_end": period_end,
        "opened_by_user_id": uid,
        "finalized_by_user_id": None,
        "status": "OPEN",
        "gross_redemptions_cents": 0,
        "interchange_fee_cents": 0,
        "net_payout_cents": 0,
        "provisional_net_payout_cents": 0,
    })
    db["sbatches"][sb["id"]] = sb
    # sweep merchant's unsettled POSTED redemptions
    for c in merchant_cards(merchant_id):
        for e in db["ledger"].values():
            if (e["gift_card_id"] == c["id"] and e["entry_type"] == "REDEMPTION"
                    and e["status"] == "POSTED" and e["settlement_batch_id"] is None):
                e["settlement_batch_id"] = sb["id"]
    # provisional payout = over ALL swept redemptions (all POSTED at this moment)
    recompute_batch_final(sb)
    sb["provisional_net_payout_cents"] = sb["net_payout_cents"]
    # advance merchant version
    touch(m)
    return ok(ser_sbatch(sb), "object", 201)


@app.route("/settlement-batches/<batch_id>", methods=["GET"])
def get_settlement(batch_id):
    auth(["Any"])
    sb = get_or_404("sbatches", batch_id)
    return ok(ser_sbatch(sb), "object", 200)


@app.route("/settlement-batches", methods=["GET"])
def list_settlements():
    auth(["Any"])
    items = list(db["sbatches"].values())
    mid = request.args.get("merchant_id")
    st = request.args.get("status")
    if mid is not None:
        items = [s for s in items if s["merchant_id"] == mid]
    if st is not None:
        items = [s for s in items if s["status"] == st]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([ser_sbatch(s) for s in page], "array", 200, meta)


@app.route("/settlement-batches/<batch_id>/finalize", methods=["POST"])
def finalize_settlement(batch_id):
    uid, role = auth(["SettlementOfficer"])
    sb = get_or_404("sbatches", batch_id)
    if sb["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    if uid == sb["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "opener may not finalize")
    m = db["merchants"].get(sb["merchant_id"])
    if not m or m["status"] != "ACTIVE":
        raise ApiError("ERR_MERCHANT_NOT_ACTIVE", 409, "merchant not active")
    recompute_batch_final(sb)
    sb["finalized_by_user_id"] = uid
    sb["status"] = "FINALIZED"
    touch(sb)
    return ok(ser_sbatch(sb), "object", 200)


@app.route("/settlement-batches/<batch_id>/cancel", methods=["POST"])
def cancel_settlement(batch_id):
    uid, role = auth(["SettlementOfficer"])
    sb = get_or_404("sbatches", batch_id)
    if sb["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    # release swept redemptions
    for e in db["ledger"].values():
        if e["settlement_batch_id"] == sb["id"]:
            e["settlement_batch_id"] = None
    sb["status"] = "CANCELLED"
    touch(sb)
    return ok(ser_sbatch(sb), "object", 200)


# =============================================================================
# EscheatReport
# =============================================================================
def capture_escheat_cards(merchant_id, period_start, period_end):
    captured = []
    for c in merchant_cards(merchant_id):
        if (c["status"] == "EXPIRED" and c["expires_at"] is not None
                and c["expires_at"] >= period_start and c["expires_at"] < period_end):
            captured.append(c)
    return captured


@app.route("/escheat-reports", methods=["POST"])
def create_escheat():
    uid, role = auth(["SettlementOfficer"])
    b = body()
    merchant_id = b.get("merchant_id")
    if isinstance(merchant_id, str):
        get_or_404("merchants", merchant_id)
    if not isinstance(merchant_id, str):
        raise ApiError("ERR_VALIDATION", 400, "merchant_id required")
    jurisdiction = b.get("jurisdiction")
    if not isinstance(jurisdiction, str) or jurisdiction == "":
        raise ApiError("ERR_VALIDATION", 400, "jurisdiction required")
    if "period_start" not in b or "period_end" not in b:
        raise ApiError("ERR_VALIDATION", 400, "period_start and period_end required")
    period_start = parse_dt(b["period_start"])
    period_end = parse_dt(b["period_end"])
    # period_end must be at or before current clock (priority 16)
    if period_end > now():
        raise ApiError("ERR_ESCHEAT_PERIOD_OPEN", 409, "escheat period still open")
    captured = capture_escheat_cards(merchant_id, period_start, period_end)
    r = make_common()
    r.update({
        "merchant_id": merchant_id,
        "jurisdiction": jurisdiction,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "escheat_total_cents": sum(balance(c["id"]) for c in captured),
        "card_count": len(captured),
        "captured_card_ids": [c["id"] for c in captured],
    })
    db["ereports"][r["id"]] = r
    return ok(ser_ereport(r), "object", 201)


@app.route("/escheat-reports/<report_id>", methods=["GET"])
def get_escheat(report_id):
    auth(["Any"])
    r = get_or_404("ereports", report_id)
    return ok(ser_ereport(r), "object", 200)


@app.route("/escheat-reports", methods=["GET"])
def list_escheat():
    auth(["Any"])
    items = list(db["ereports"].values())
    mid = request.args.get("merchant_id")
    jur = request.args.get("jurisdiction")
    st = request.args.get("status")
    if mid is not None:
        items = [r for r in items if r["merchant_id"] == mid]
    if jur is not None:
        items = [r for r in items if r["jurisdiction"] == jur]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([ser_ereport(r) for r in page], "array", 200, meta)


@app.route("/escheat-reports/<report_id>/remit", methods=["POST"])
def remit_escheat(report_id):
    uid, role = auth(["SettlementOfficer"])
    r = get_or_404("ereports", report_id)
    if r["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "invalid state")
    m = db["merchants"].get(r["merchant_id"])
    if not m or m["status"] != "ACTIVE":
        raise ApiError("ERR_MERCHANT_NOT_ACTIVE", 409, "merchant not active")
    for cid in r["captured_card_ids"]:
        c = db["cards"].get(cid)
        if not c or c["status"] != "EXPIRED":
            continue
        bal = balance(c["id"])
        if bal > 0:
            post_ledger(c["id"], "ESCHEAT_REMIT", -bal, "escheat remittance")
        c["status"] = "ESCHEATED"
        touch(c)
    r["status"] = "REMITTED"
    touch(r)
    return ok(ser_ereport(r), "object", 200)


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
