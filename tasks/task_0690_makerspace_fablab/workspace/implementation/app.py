"""
Makerspace & Fab-Lab Membership API — single-file Flask implementation.

Every behavior traces to a sentence in workspace/PRD.md. Storage is in-memory only
(wiped on every process restart). A logical clock (default 2026-04-01T00:00:00Z)
drives all time-dependent rules.
"""
import os
import re
import uuid
import string
import random
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, g, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (PRD §2.3, §3.x, §1.3 calculations)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

ROLES = {"Member", "StaffInstructor", "FacilityAdmin"}
MACHINE_CLASSES = {"LASER", "CNC", "PRINTER_3D"}
BILLING_MODES = {"DAYPASS", "MONTHLY"}
SUPERVISION_MODES = {"SUPERVISED", "UNSUPERVISED"}
OPERATIONAL_STATUSES = {"AVAILABLE", "OUT_OF_SERVICE"}

CYCLE_DAYS = 30
CERT_VALID_DAYS = 365
READINESS_GATE = Decimal("0.8")
MAX_DAYPASSES_PER_WINDOW = 3
OVERAGE_RATE_CENTS_PER_LITER = 30
MINUTES_PER_HOUR = 60
BPS_DENOMINATOR = 10000

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
_lock = threading.RLock()


def _parse_iso(value):
    """Parse an ISO 8601 instant (with optional Z) to an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Clock:
    def __init__(self):
        self.now = _parse_iso(DEFAULT_CLOCK_ISO)

    def set(self, iso):
        self.now = _parse_iso(iso)


clock = Clock()

# Monotonic insertion sequence — stable tiebreaker when multiple records share
# the same logical-clock created_at. Not serialized; used only for list ordering
# so that created_at-ascending lists preserve insertion order on ties
# (PRD §2.3 sort by created_at asc; §2.4 created_at is the append-only key).
_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]

# ---------------------------------------------------------------------------
# In-memory store (PRD §2 — starts empty on every boot, never seeded)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.membership_tiers = {}
        self.members = {}
        self.machines = {}
        self.certifications = {}
        self.reservations = {}
        self.lockers = {}
        self.material_items = {}
        self.material_purchases = {}
        self.workshops = {}
        self.workshop_enrollments = {}
        self.wallet_entries = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Errors (PRD §2.6, §5)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": _fmt_iso(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, list_meta=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(list_meta),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def _handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    return error_response("ERR_INTERNAL", 500, str(e))


# ---------------------------------------------------------------------------
# Money / rounding helpers (PRD §2.8)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal to a whole integer using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD §2.1, §2.6)
# ---------------------------------------------------------------------------
def require_auth():
    """Validate X-User-ID and X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return user_id, role


def get_auth():
    return g.get("user_id"), g.get("role")


# ---------------------------------------------------------------------------
# Field/body helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            err("ERR_INVALID_REQUEST", 422, "Request body must be a JSON object")
        return data
    return {}


def require_int_nonneg(body, field, default=None, required=False):
    if field not in body or body[field] is None:
        if required:
            err("ERR_INVALID_REQUEST", 422, f"Missing required field: {field}")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        err("ERR_INVALID_REQUEST", 422, f"{field} must be an integer")
    if val < 0:
        err("ERR_INVALID_REQUEST", 422, f"{field} must be non-negative")
    return val


def require_int(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            err("ERR_INVALID_REQUEST", 422, f"Missing required field: {field}")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        err("ERR_INVALID_REQUEST", 422, f"{field} must be an integer")
    return val


def require_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            err("ERR_INVALID_REQUEST", 422, f"Missing required field: {field}")
        return None
    val = body[field]
    if not isinstance(val, str) or val == "":
        err("ERR_INVALID_REQUEST", 422, f"{field} must be a non-empty string")
    return val


def require_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        err("ERR_INVALID_REQUEST", 422, f"{field} must be a boolean")
    return val


def require_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            err("ERR_INVALID_REQUEST", 422, f"Missing required field: {field}")
        return default
    val = body[field]
    if val not in allowed:
        err("ERR_INVALID_REQUEST", 422, f"{field} must be one of {sorted(allowed)}")
    return val


def require_datetime(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            err("ERR_INVALID_REQUEST", 422, f"Missing required field: {field}")
        return None
    try:
        return _parse_iso(body[field])
    except Exception:
        err("ERR_INVALID_REQUEST", 422, f"{field} must be an ISO 8601 datetime")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_VALIDATION_LIMIT", 400, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            err("ERR_VALIDATION_LIMIT", 400, "limit out of range")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_VALIDATION_LIMIT", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION_LIMIT", 400, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by created_at asc (PRD §2.3), apply limit/offset, return (page, meta)."""
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(items)
    page = items[offset: offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# Common system fields (PRD §2.4, §2.9)
# ---------------------------------------------------------------------------
def stamp_create(rec, versioned=True):
    now = _fmt_iso(clock.now)
    rec["created_at"] = now
    rec["_seq"] = next_seq()
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on mutation (PRD §2.4, §2.9)."""
    rec["updated_at"] = _fmt_iso(clock.now)
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Lookups (PRD §2.6 existence, §2.7 FK resolution)
# ---------------------------------------------------------------------------
def find(collection, _id):
    return collection.get(_id)


def must_find(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        err("ERR_NOT_FOUND", 404, "Resource not found")
    return rec


# ===========================================================================
# Calculations (PRD §3.11)
# ===========================================================================
def tier_of_member(member):
    return db.membership_tiers.get(member["tier_id"])


def compute_readiness(cert):
    """certification_readiness (PRD §3.4)."""
    cert_weight = Decimal("0.5") if cert["status"] == "ACTIVE" else Decimal("0.0")
    orientation_weight = Decimal("0.2") if cert["orientation_complete"] else Decimal("0.0")
    required = cert["required_supervised_minutes"]
    if required and required > 0:
        ratio = Decimal(cert["supervised_minutes"]) / Decimal(required)
        if ratio > 1:
            ratio = Decimal("1")
    else:
        ratio = Decimal("0")
    supervised_weight = Decimal("0.3") * ratio
    total = cert_weight + orientation_weight + supervised_weight
    score = total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(score)


def session_charge(machine, tier, prepaid_remaining, basis_minutes):
    """
    session_charge calc (PRD §3.11). Returns (charge_cents, free_minutes_applied).
    Single round-half-up after discount on time charge; setup added after rounding.
    """
    billable_minutes = max(basis_minutes, machine["min_billing_minutes"])
    free_minutes = min(billable_minutes, prepaid_remaining)
    charged_minutes = billable_minutes - free_minutes
    time_charge_raw = (Decimal(charged_minutes) * Decimal(machine["hourly_rate_cents"])) / Decimal(MINUTES_PER_HOUR)
    disc_bps = tier["discount_bps"] if tier else 0
    time_after_disc = time_charge_raw * (Decimal(BPS_DENOMINATOR) - Decimal(disc_bps)) / Decimal(BPS_DENOMINATOR)
    time_charge_cents = round_half_up(time_after_disc)
    session = time_charge_cents + machine["setup_fee_cents"]
    return session, free_minutes


def material_totals(lines, tier, waste_surcharge_bps):
    """material_billing calc (PRD §3.11). Round per line, sum, surcharge, round once."""
    disc_bps = tier["discount_bps"] if tier else 0
    subtotal = 0
    for line in lines:
        item = db.material_items[line["material_item_id"]]
        raw_line = Decimal(line["quantity"]) * Decimal(item["unit_price_cents"])
        disc_line = raw_line * (Decimal(BPS_DENOMINATOR) - Decimal(disc_bps)) / Decimal(BPS_DENOMINATOR)
        line_cents = round_half_up(disc_line)
        subtotal += line_cents
    surcharge = round_half_up(Decimal(subtotal) * Decimal(waste_surcharge_bps) / Decimal(BPS_DENOMINATOR))
    total = subtotal + surcharge
    return subtotal, surcharge, total


def forward_proration(tier):
    """membership_proration FORWARD variant (PRD §3.11). Full monthly fee."""
    return round_half_up(Decimal(tier["monthly_fee_cents"]) * Decimal(CYCLE_DAYS) / Decimal(CYCLE_DAYS))


def chronological_refund(member, tier):
    """membership_proration CHRONOLOGICAL variant (PRD §3.11). Returns refund_cents."""
    forward_cents = forward_proration(tier)
    cycle_start = _parse_iso(member["cycle_start_at"])
    elapsed_seconds = (clock.now - cycle_start).total_seconds()
    elapsed_days = int(elapsed_seconds // 86400)
    if elapsed_days < 0:
        elapsed_days = 0
    used_days = min(elapsed_days, CYCLE_DAYS)
    accrued = round_half_up(Decimal(tier["monthly_fee_cents"]) * Decimal(used_days) / Decimal(CYCLE_DAYS))
    return forward_cents - accrued


def locker_overage(locker, member):
    """locker_overage calc (PRD §3.7)."""
    tier = tier_of_member(member)
    free = tier["locker_free_liters"] if tier else 0
    overage_liters = max(0, locker["used_liters"] - free)
    return overage_liters * OVERAGE_RATE_CENTS_PER_LITER


# ===========================================================================
# Wallet ledger (PRD §2.8)
# ===========================================================================
def append_wallet_entry(member, kind, amount_cents, reservation_id=None):
    entry_id = new_id()
    entry = {
        "id": entry_id,
        "member_id": member["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "reservation_id": reservation_id if kind in ("DEBIT", "REFUND") else None,
        "balance_after_cents": member["wallet_credit_cents"],
        "created_at": _fmt_iso(clock.now),
        "_seq": next_seq(),
    }
    db.wallet_entries[entry_id] = entry
    return entry


def credit_wallet(member, amount, kind, reservation_id=None):
    member["wallet_credit_cents"] += amount
    append_wallet_entry(member, kind, amount, reservation_id)


def debit_wallet(member, amount, kind, reservation_id=None):
    member["wallet_credit_cents"] -= amount
    append_wallet_entry(member, kind, -amount, reservation_id)


# ===========================================================================
# Serialization — return all declared fields per entity
# ===========================================================================
def serialize(rec):
    """Records are stored as plain dicts already matching the response shape.

    The internal `_seq` ordering key is never exposed in responses.
    """
    return {k: v for k, v in rec.items() if k != "_seq"}


# ===========================================================================
# Ownership checks (PRD §2.1)
# ===========================================================================
def assert_member_owns(resource_member_id):
    """Entity-backed Member role may act only on their own resources."""
    user_id, role = get_auth()
    if role == "Member" and resource_member_id != user_id:
        err("ERR_FORBIDDEN", 403, "Member may act only on their own resources")


def assert_role_in(allowed):
    user_id, role = get_auth()
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, f"Role {role} not permitted for this operation")


# ===========================================================================
# Route registration helper for auth precedence
# ===========================================================================
@app.before_request
def _before():
    g.user_id = None
    g.role = None
    path = request.path
    # Auth exceptions (PRD §2.1): self-service registration + clock set.
    is_register = (request.method == "POST" and path == "/members")
    is_clock = (request.method == "POST" and path == "/_clock/set_current_utc")
    if is_register or is_clock:
        # These do not require validated auth headers.
        g.user_id = request.headers.get("X-User-ID")
        g.role = request.headers.get("X-User-Role")
        return None
    # OPTIONS / favicon etc. — let routing handle; but enforce auth on real routes.
    if request.method == "OPTIONS":
        return None
    user_id, role = require_auth()
    g.user_id = user_id
    g.role = role
    return None


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # FacilityAdmin per PRD §4, but auth is not validated for this endpoint (§2.1).
    body = get_body()
    iso = body.get("to_iso8601")
    if not iso:
        err("ERR_INVALID_REQUEST", 422, "Missing required field: to_iso8601")
    try:
        clock.set(iso)
    except Exception:
        err("ERR_INVALID_REQUEST", 422, "to_iso8601 must be an ISO 8601 datetime")
    return ok({"now_utc": _fmt_iso(clock.now)}, 200)


# ===========================================================================
# MEMBERSHIP TIERS (PRD §3.1)
# ===========================================================================
@app.route("/membership-tiers", methods=["POST"])
def create_tier():
    assert_role_in({"FacilityAdmin"})
    body = get_body()
    code = require_str(body, "code")
    name = require_str(body, "name")
    billing_mode = require_enum(body, "billing_mode", BILLING_MODES)
    monthly_fee = require_int_nonneg(body, "monthly_fee_cents", default=0)
    daypass_fee = require_int_nonneg(body, "daypass_fee_cents", default=0)
    discount_bps = require_int_nonneg(body, "discount_bps", default=0)
    if discount_bps > 10000:
        err("ERR_INVALID_REQUEST", 422, "discount_bps must be 0..10000")
    prepaid_minutes = require_int_nonneg(body, "prepaid_machine_minutes", default=0)
    locker_free = require_int_nonneg(body, "locker_free_liters", default=0)
    unsupervised = require_bool(body, "unsupervised_allowed", default=False)

    for t in db.membership_tiers.values():
        if t["code"] == code:
            err("ERR_DUPLICATE_TIER_CODE", 409, "Tier code already exists")

    tid = new_id()
    rec = {
        "id": tid,
        "code": code,
        "name": name,
        "billing_mode": billing_mode,
        "monthly_fee_cents": monthly_fee,
        "daypass_fee_cents": daypass_fee,
        "discount_bps": discount_bps,
        "prepaid_machine_minutes": prepaid_minutes,
        "locker_free_liters": locker_free,
        "unsupervised_allowed": unsupervised,
    }
    stamp_create(rec)
    db.membership_tiers[tid] = rec
    return ok(serialize(rec), 201)


@app.route("/membership-tiers/<id>", methods=["GET"])
def get_tier(id):
    rec = must_find(db.membership_tiers, id)
    return ok(serialize(rec), 200)


@app.route("/membership-tiers", methods=["GET"])
def list_tiers():
    page, meta = paginate(list(db.membership_tiers.values()))
    return ok([serialize(r) for r in page], 200, meta)


# ===========================================================================
# MEMBERS (PRD §3.2, §3.3, §3.10)
# ===========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    # Self-service / FacilityAdmin (PRD §2.1, §4). No auth validation required.
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    tier_id = require_str(body, "tier_id")
    must_find(db.membership_tiers, tier_id)

    mid = new_id()
    rec = {
        "id": mid,
        "email": email,
        "full_name": full_name,
        "tier_id": tier_id,
        "subscription_status": "PENDING_WAIVER",
        "waiver_signed_at": None,
        "cycle_start_at": None,
        "wallet_credit_cents": 0,
        "prepaid_minutes_remaining": 0,
        "daypass_count_window": 0,
    }
    stamp_create(rec)
    db.members[mid] = rec
    return ok(serialize(rec), 201)


@app.route("/members/<id>", methods=["GET"])
def get_member(id):
    rec = must_find(db.members, id)
    return ok(serialize(rec), 200)


@app.route("/members", methods=["GET"])
def list_members():
    assert_role_in({"StaffInstructor", "FacilityAdmin"})
    items = list(db.members.values())
    tier_id = request.args.get("tier_id")
    if tier_id is not None:
        items = [m for m in items if m["tier_id"] == tier_id]
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@app.route("/members/<id>/sign-waiver", methods=["POST"])
def sign_waiver(id):
    assert_role_in({"Member"})
    rec = must_find(db.members, id)
    assert_member_owns(rec["id"])
    rec["waiver_signed_at"] = _fmt_iso(clock.now)
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/members/<id>/topup", methods=["POST"])
def topup(id):
    assert_role_in({"Member", "FacilityAdmin"})
    rec = must_find(db.members, id)
    assert_member_owns(rec["id"])
    body = get_body()
    amount = require_int(body, "amount_cents", required=True)
    if amount <= 0:
        err("ERR_INVALID_REQUEST", 422, "amount_cents must be positive")
    credit_wallet(rec, amount, "TOPUP")
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/members/<id>/activate", methods=["POST"])
def activate(id):
    assert_role_in({"Member"})
    rec = must_find(db.members, id)
    assert_member_owns(rec["id"])
    status = rec["subscription_status"]

    if status == "PENDING_WAIVER":
        # waiver before tier resolution per §3.2 / precedence (state then safety).
        if status not in ("PENDING_WAIVER",):
            err("ERR_INVALID_STATE", 409, "Cannot activate from current state")
        if rec["waiver_signed_at"] is None:
            err("ERR_WAIVER_REQUIRED", 409, "Waiver must be signed before activation")
        tier = tier_of_member(rec)
        if tier is None:
            err("ERR_NOT_FOUND", 404, "Member tier does not resolve")
        if tier["billing_mode"] == "MONTHLY":
            forward_cents = forward_proration(tier)
            if rec["wallet_credit_cents"] < forward_cents:
                err("ERR_INSUFFICIENT_FUNDS", 409, "Insufficient funds for monthly fee")
            rec["cycle_start_at"] = _fmt_iso(clock.now)
            rec["prepaid_minutes_remaining"] = tier["prepaid_machine_minutes"]
            debit_wallet(rec, forward_cents, "SUBSCRIPTION")
        else:
            rec["cycle_start_at"] = _fmt_iso(clock.now)
            rec["prepaid_minutes_remaining"] = tier["prepaid_machine_minutes"]
        rec["subscription_status"] = "ACTIVE"
        touch(rec)
        return ok(serialize(rec), 200)

    if status == "SUSPENDED":
        if rec["waiver_signed_at"] is None:
            err("ERR_WAIVER_REQUIRED", 409, "Waiver must be signed before activation")
        # No re-proration; cycle_start_at unchanged (PRD §3.2).
        rec["subscription_status"] = "ACTIVE"
        touch(rec)
        return ok(serialize(rec), 200)

    err("ERR_INVALID_STATE", 409, "Cannot activate from current state")


@app.route("/members/<id>/suspend", methods=["POST"])
def suspend(id):
    assert_role_in({"StaffInstructor", "FacilityAdmin"})
    rec = must_find(db.members, id)
    if rec["subscription_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Only ACTIVE members may be suspended")
    rec["subscription_status"] = "SUSPENDED"
    touch(rec)
    # Cascade A: cancel HELD/CONFIRMED reservations, refunding each hold.
    for resv in list(db.reservations.values()):
        if resv["member_id"] == rec["id"] and resv["occupancy_status"] in ("HELD", "CONFIRMED"):
            _cancel_reservation_internal(resv, rec)
    return ok(serialize(rec), 200)


@app.route("/members/<id>/cancel", methods=["POST"])
def cancel_member(id):
    assert_role_in({"Member"})
    rec = must_find(db.members, id)
    assert_member_owns(rec["id"])
    if rec["subscription_status"] == "CANCELLED":
        err("ERR_INVALID_STATE", 409, "Member already cancelled")
    prior_status = rec["subscription_status"]
    tier = tier_of_member(rec)

    rec["subscription_status"] = "CANCELLED"
    touch(rec)

    # Cancel HELD/CONFIRMED/CHECKED_IN reservations, refund holds.
    for resv in list(db.reservations.values()):
        if resv["member_id"] == rec["id"] and resv["occupancy_status"] in ("HELD", "CONFIRMED", "CHECKED_IN"):
            _cancel_reservation_internal(resv, rec)

    # Release ASSIGNED lockers.
    for locker in list(db.lockers.values()):
        if locker["member_id"] == rec["id"] and locker["status"] == "ASSIGNED":
            locker["status"] = "RELEASED"
            locker["used_liters"] = 0
            locker["overage_fee_cents"] = locker_overage(locker, rec)
            touch(locker)

    # Chronological proration refund for MONTHLY tier when was ACTIVE/SUSPENDED.
    if prior_status in ("ACTIVE", "SUSPENDED") and tier and tier["billing_mode"] == "MONTHLY":
        refund = chronological_refund(rec, tier)
        if refund != 0:
            credit_wallet(rec, refund, "SUBSCRIPTION")
            touch(rec)

    return ok(serialize(rec), 200)


@app.route("/members/<id>/buy-daypass", methods=["POST"])
def buy_daypass(id):
    assert_role_in({"Member"})
    rec = must_find(db.members, id)
    assert_member_owns(rec["id"])
    tier = tier_of_member(rec)
    # Rolling-window threshold (PRD §3.3): 4th blocked.
    if rec["daypass_count_window"] >= MAX_DAYPASSES_PER_WINDOW:
        err("ERR_CONVERT_TO_MONTHLY", 409, "Day-pass limit reached in rolling window")
    fee = tier["daypass_fee_cents"] if tier else 0
    rec["daypass_count_window"] += 1
    debit_wallet(rec, fee, "DAYPASS")
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/members/<id>/roll-cycle", methods=["POST"])
def roll_cycle(id):
    assert_role_in({"FacilityAdmin"})
    rec = must_find(db.members, id)
    tier = tier_of_member(rec)
    rec["cycle_start_at"] = _fmt_iso(clock.now)
    rec["prepaid_minutes_remaining"] = tier["prepaid_machine_minutes"] if tier else 0
    rec["daypass_count_window"] = 0
    touch(rec)
    return ok(serialize(rec), 200)


# ===========================================================================
# WALLET ENTRIES (PRD §2.8)
# ===========================================================================
@app.route("/wallet-entries/<id>", methods=["GET"])
def get_wallet_entry(id):
    rec = must_find(db.wallet_entries, id)
    return ok(serialize(rec), 200)


@app.route("/wallet-entries", methods=["GET"])
def list_wallet_entries():
    items = list(db.wallet_entries.values())
    member_id = request.args.get("member_id")
    reservation_id = request.args.get("reservation_id")
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    if reservation_id is not None:
        items = [e for e in items if e.get("reservation_id") == reservation_id]
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


# ===========================================================================
# MACHINES (PRD §3.1)
# ===========================================================================
@app.route("/machines", methods=["POST"])
def create_machine():
    assert_role_in({"FacilityAdmin"})
    body = get_body()
    name = require_str(body, "name")
    machine_class = require_enum(body, "machine_class", MACHINE_CLASSES)
    hourly_rate = require_int_nonneg(body, "hourly_rate_cents", required=True)
    setup_fee = require_int_nonneg(body, "setup_fee_cents", default=0)
    min_billing = require_int_nonneg(body, "min_billing_minutes", default=0)
    cooldown = require_int_nonneg(body, "cooldown_minutes", default=0)
    requires_cert = require_bool(body, "requires_certification", default=True)

    mid = new_id()
    rec = {
        "id": mid,
        "name": name,
        "machine_class": machine_class,
        "hourly_rate_cents": hourly_rate,
        "setup_fee_cents": setup_fee,
        "min_billing_minutes": min_billing,
        "cooldown_minutes": cooldown,
        "requires_certification": requires_cert,
        "operational_status": "AVAILABLE",
    }
    stamp_create(rec)
    db.machines[mid] = rec
    return ok(serialize(rec), 201)


@app.route("/machines/<id>", methods=["GET"])
def get_machine(id):
    rec = must_find(db.machines, id)
    return ok(serialize(rec), 200)


@app.route("/machines", methods=["GET"])
def list_machines():
    items = list(db.machines.values())
    machine_class = request.args.get("machine_class")
    if machine_class is not None:
        items = [m for m in items if m["machine_class"] == machine_class]
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@app.route("/machines/<id>/set-status", methods=["POST"])
def set_machine_status(id):
    assert_role_in({"FacilityAdmin"})
    rec = must_find(db.machines, id)
    body = get_body()
    status = require_enum(body, "operational_status", OPERATIONAL_STATUSES)
    rec["operational_status"] = status
    touch(rec)
    return ok(serialize(rec), 200)


# ===========================================================================
# CERTIFICATIONS (PRD §3.4)
# ===========================================================================
def _mint_certification(member_id, machine_class, orientation_complete,
                        supervised_minutes, required_supervised_minutes):
    cid = new_id()
    granted = clock.now
    expires = granted + timedelta(days=CERT_VALID_DAYS)
    rec = {
        "id": cid,
        "member_id": member_id,
        "machine_class": machine_class,
        "status": "ACTIVE",
        "orientation_complete": orientation_complete,
        "supervised_minutes": supervised_minutes,
        "required_supervised_minutes": required_supervised_minutes,
        "granted_at": _fmt_iso(granted),
        "expires_at": _fmt_iso(expires),
        "readiness_score": 0.0,
    }
    rec["readiness_score"] = compute_readiness(rec)
    stamp_create(rec)
    db.certifications[cid] = rec
    return rec


@app.route("/certifications", methods=["POST"])
def create_certification():
    assert_role_in({"StaffInstructor", "FacilityAdmin"})
    body = get_body()
    member_id = require_str(body, "member_id")
    machine_class = require_enum(body, "machine_class", MACHINE_CLASSES)
    must_find(db.members, member_id)
    orientation = require_bool(body, "orientation_complete", default=False)
    supervised = require_int_nonneg(body, "supervised_minutes", default=0)
    required = require_int_nonneg(body, "required_supervised_minutes", default=0)
    rec = _mint_certification(member_id, machine_class, orientation, supervised, required)
    return ok(serialize(rec), 201)


@app.route("/certifications/<id>", methods=["GET"])
def get_certification(id):
    rec = must_find(db.certifications, id)
    return ok(serialize(rec), 200)


@app.route("/certifications", methods=["GET"])
def list_certifications():
    items = list(db.certifications.values())
    member_id = request.args.get("member_id")
    machine_class = request.args.get("machine_class")
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if machine_class is not None:
        items = [c for c in items if c["machine_class"] == machine_class]
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@app.route("/certifications/<id>/refresh-expiry", methods=["POST"])
def refresh_expiry(id):
    assert_role_in({"StaffInstructor", "FacilityAdmin"})
    rec = must_find(db.certifications, id)
    # ACTIVE -> EXPIRED only when ACTIVE and clock now >= expires_at.
    if rec["status"] != "ACTIVE" or clock.now < _parse_iso(rec["expires_at"]):
        err("ERR_INVALID_STATE", 409, "Certification not eligible to expire")
    rec["status"] = "EXPIRED"
    rec["readiness_score"] = compute_readiness(rec)
    touch(rec)
    # Cascade B step 1: cancel future UNSUPERVISED HELD/CONFIRMED reservations
    # on this member + machine_class (start_at > clock now).
    for resv in list(db.reservations.values()):
        if (resv["member_id"] == rec["member_id"]
                and resv["supervision_mode"] == "UNSUPERVISED"
                and resv["occupancy_status"] in ("HELD", "CONFIRMED")
                and _parse_iso(resv["start_at"]) > clock.now):
            machine = db.machines.get(resv["machine_id"])
            if machine and machine["machine_class"] == rec["machine_class"]:
                member = db.members.get(resv["member_id"])
                _cancel_reservation_internal(resv, member)
    return ok(serialize(rec), 200)


@app.route("/certifications/<id>/renew", methods=["POST"])
def renew_certification(id):
    assert_role_in({"StaffInstructor", "FacilityAdmin"})
    rec = must_find(db.certifications, id)
    if rec["status"] != "EXPIRED":
        err("ERR_INVALID_STATE", 409, "Only EXPIRED certifications may be renewed")
    granted = clock.now
    rec["status"] = "ACTIVE"
    rec["granted_at"] = _fmt_iso(granted)
    rec["expires_at"] = _fmt_iso(granted + timedelta(days=CERT_VALID_DAYS))
    rec["readiness_score"] = compute_readiness(rec)
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/certifications/<id>/revoke", methods=["POST"])
def revoke_certification(id):
    assert_role_in({"StaffInstructor", "FacilityAdmin"})
    rec = must_find(db.certifications, id)
    if rec["status"] == "REVOKED":
        err("ERR_INVALID_STATE", 409, "Certification already revoked")
    rec["status"] = "REVOKED"
    rec["readiness_score"] = compute_readiness(rec)
    touch(rec)
    # Cancel HELD/CONFIRMED reservations on this member + machine_class.
    for resv in list(db.reservations.values()):
        if (resv["member_id"] == rec["member_id"]
                and resv["occupancy_status"] in ("HELD", "CONFIRMED")):
            machine = db.machines.get(resv["machine_id"])
            if machine and machine["machine_class"] == rec["machine_class"]:
                member = db.members.get(resv["member_id"])
                _cancel_reservation_internal(resv, member)
    return ok(serialize(rec), 200)


# ===========================================================================
# RESERVATIONS (PRD §3.5, §3.6)
# ===========================================================================
def _reserved_minutes(start_at, end_at):
    return int((end_at - start_at).total_seconds() // 60)


def _intervals_overlap(new_start, new_end, ex_start, ex_end, cooldown_minutes):
    """
    Half-open overlap (PRD §3.5). If cooldown>0, dilate only the EXISTING window's
    end by cooldown_minutes before comparison, so a new booking must leave at least
    that buffer AFTER any neighbor (the buffer is one-sided, not symmetric).
    """
    ex_end_dilated = ex_end + timedelta(minutes=cooldown_minutes)
    # bare half-open: overlap iff new_start < ex_end_dilated and ex_start < new_end
    return new_start < ex_end_dilated and ex_start < new_end


def _check_overlap(machine, member_id, start_at, end_at, exclude_id=None):
    cooldown = machine["cooldown_minutes"]
    for resv in db.reservations.values():
        if resv["id"] == exclude_id:
            continue
        if resv["machine_id"] != machine["id"]:
            continue
        if resv["occupancy_status"] in ("COMPLETED", "CANCELLED", "NO_SHOW"):
            continue
        ex_start = _parse_iso(resv["start_at"])
        ex_end = _parse_iso(resv["end_at"])
        if _intervals_overlap(start_at, end_at, ex_start, ex_end, cooldown):
            err("ERR_RESERVATION_OVERLAP", 409, "Reservation window collides")


@app.route("/reservations", methods=["POST"])
def create_reservation():
    assert_role_in({"Member"})
    body = get_body()
    member_id = require_str(body, "member_id")
    machine_id = require_str(body, "machine_id")
    supervision_mode = require_enum(body, "supervision_mode", SUPERVISION_MODES)
    # FK resolution left-to-right (PRD §2.7): member, machine, certification.
    member = must_find(db.members, member_id)
    assert_member_owns(member_id)
    machine = must_find(db.machines, machine_id)
    certification_id = body.get("certification_id")
    if certification_id is not None:
        if not isinstance(certification_id, str):
            err("ERR_INVALID_REQUEST", 422, "certification_id must be a string")
        must_find(db.certifications, certification_id)
    start_at = require_datetime(body, "start_at")
    end_at = require_datetime(body, "end_at")
    if not (end_at > start_at):
        err("ERR_INVALID_REQUEST", 422, "end_at must be strictly after start_at")

    # Overlap at creation (PRD §3.5).
    _check_overlap(machine, member_id, start_at, end_at)

    rid = new_id()
    rec = {
        "id": rid,
        "member_id": member_id,
        "machine_id": machine_id,
        "certification_id": certification_id,
        "start_at": _fmt_iso(start_at),
        "end_at": _fmt_iso(end_at),
        "supervision_mode": supervision_mode,
        "occupancy_status": "HELD",
        "billing_status": "UNBILLED",
        "reserved_minutes": _reserved_minutes(start_at, end_at),
        "actual_minutes": None,
        "check_in_at": None,
        "check_out_at": None,
        "free_minutes_applied": 0,
        "estimate_charge_cents": 0,
        "final_charge_cents": 0,
    }
    stamp_create(rec)
    db.reservations[rid] = rec
    return ok(serialize(rec), 201)


@app.route("/reservations/<id>", methods=["GET"])
def get_reservation(id):
    rec = must_find(db.reservations, id)
    return ok(serialize(rec), 200)


@app.route("/reservations", methods=["GET"])
def list_reservations():
    items = list(db.reservations.values())
    for key in ("member_id", "machine_id", "certification_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@app.route("/reservations/<id>/confirm", methods=["POST"])
def confirm_reservation(id):
    assert_role_in({"Member"})
    rec = must_find(db.reservations, id)
    assert_member_owns(rec["member_id"])
    body = get_body()
    # expected_member_version required for OCC (PRD §2.5).
    if "expected_member_version" not in body or body["expected_member_version"] is None:
        err("ERR_INVALID_REQUEST", 422, "Missing required field: expected_member_version")
    expected = body["expected_member_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_INVALID_REQUEST", 422, "expected_member_version must be an integer")

    member = db.members.get(rec["member_id"])
    machine = db.machines.get(rec["machine_id"])

    # OCC (precedence 5, before state). PRD §2.6.
    if member["version"] != expected:
        err("ERR_STALE_VERSION", 412, "Stale member version")

    # State (precedence 6).
    if rec["occupancy_status"] != "HELD":
        err("ERR_INVALID_STATE", 409, "Reservation not HELD")

    # Business safety / temporal / fiscal in §3.6 narrative order.
    if member["subscription_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Member not ACTIVE")
    if member["waiver_signed_at"] is None:
        err("ERR_WAIVER_REQUIRED", 409, "Waiver required")
    if machine["operational_status"] != "AVAILABLE":
        err("ERR_MACHINE_OUT_OF_SERVICE", 409, "Machine out of service")

    cert = None
    if machine["requires_certification"]:
        cid = rec["certification_id"]
        cert = db.certifications.get(cid) if cid else None
        if (cert is None
                or cert["member_id"] != member["id"]
                or cert["machine_class"] != machine["machine_class"]
                or cert["status"] != "ACTIVE"):
            err("ERR_CERTIFICATION_REQUIRED", 409, "Active certification required")
    else:
        cid = rec["certification_id"]
        if cid:
            cert = db.certifications.get(cid)

    if rec["supervision_mode"] == "UNSUPERVISED":
        tier = tier_of_member(member)
        ready = cert is not None and Decimal(str(cert["readiness_score"])) >= READINESS_GATE
        if not (tier and tier["unsupervised_allowed"] and ready):
            err("ERR_READINESS_NOT_MET", 409, "Unsupervised readiness not met")

    # Overlap at confirm (PRD §3.6).
    start_at = _parse_iso(rec["start_at"])
    end_at = _parse_iso(rec["end_at"])
    _check_overlap(machine, member["id"], start_at, end_at, exclude_id=rec["id"])

    # Forward estimate (PRD §3.6, §3.11).
    tier = tier_of_member(member)
    estimate, free_minutes = session_charge(
        machine, tier, member["prepaid_minutes_remaining"], rec["reserved_minutes"])

    if member["wallet_credit_cents"] < estimate:
        err("ERR_INSUFFICIENT_FUNDS", 409, "Insufficient funds for estimate")

    rec["estimate_charge_cents"] = estimate
    rec["free_minutes_applied"] = free_minutes
    rec["occupancy_status"] = "CONFIRMED"
    rec["billing_status"] = "HOLD_PLACED"
    member["prepaid_minutes_remaining"] -= free_minutes
    debit_wallet(member, estimate, "DEBIT", reservation_id=rec["id"])
    touch(member)  # advances Member.version by 1
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/reservations/<id>/release-hold", methods=["POST"])
def release_hold(id):
    assert_role_in({"Member"})
    rec = must_find(db.reservations, id)
    assert_member_owns(rec["member_id"])
    if rec["occupancy_status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409, "Reservation not CONFIRMED")
    if not (clock.now < _parse_iso(rec["start_at"])):
        err("ERR_INVALID_STATE", 409, "Cannot release after window opens")
    member = db.members.get(rec["member_id"])
    estimate = rec["estimate_charge_cents"]
    credit_wallet(member, estimate, "REFUND", reservation_id=rec["id"])
    member["prepaid_minutes_remaining"] += rec["free_minutes_applied"]
    rec["free_minutes_applied"] = 0
    rec["billing_status"] = "UNBILLED"
    rec["occupancy_status"] = "HELD"
    touch(member)
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/reservations/<id>/check-in", methods=["POST"])
def check_in(id):
    assert_role_in({"Member"})
    rec = must_find(db.reservations, id)
    assert_member_owns(rec["member_id"])
    if rec["occupancy_status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409, "Reservation not CONFIRMED")
    start_at = _parse_iso(rec["start_at"])
    end_at = _parse_iso(rec["end_at"])
    if not (clock.now >= start_at and clock.now < end_at):
        err("ERR_WINDOW_NOT_OPEN", 409, "Check-in outside the window")
    rec["check_in_at"] = _fmt_iso(clock.now)
    rec["occupancy_status"] = "CHECKED_IN"
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/reservations/<id>/check-out", methods=["POST"])
def check_out(id):
    assert_role_in({"Member"})
    rec = must_find(db.reservations, id)
    assert_member_owns(rec["member_id"])
    if rec["occupancy_status"] != "CHECKED_IN":
        err("ERR_INVALID_STATE", 409, "Reservation not CHECKED_IN")
    member = db.members.get(rec["member_id"])
    machine = db.machines.get(rec["machine_id"])
    tier = tier_of_member(member)
    check_in = _parse_iso(rec["check_in_at"])
    rec["check_out_at"] = _fmt_iso(clock.now)
    actual_minutes = int((clock.now - check_in).total_seconds() // 60)
    rec["actual_minutes"] = actual_minutes

    # FINAL variant. free_minutes_applied was already consumed at confirm; the
    # final charge recomputes against prepaid minutes that were already debited.
    # Per §3.11 final uses actual_minutes basis; the prepaid block is the same
    # already-applied free minutes (member.prepaid_minutes_remaining already
    # reflects the confirm debit). We recompute using the free minutes that were
    # applied to this reservation so the discount/prepaid math matches confirm.
    restored_prepaid = member["prepaid_minutes_remaining"] + rec["free_minutes_applied"]
    final_charge, final_free = session_charge(machine, tier, restored_prepaid, actual_minutes)
    rec["final_charge_cents"] = final_charge

    # Reconcile prepaid minutes to the final applied amount.
    delta_free = final_free - rec["free_minutes_applied"]
    member["prepaid_minutes_remaining"] -= delta_free
    rec["free_minutes_applied"] = final_free

    delta = final_charge - rec["estimate_charge_cents"]
    if delta > 0:
        debit_wallet(member, delta, "DEBIT", reservation_id=rec["id"])
        touch(member)
    elif delta < 0:
        credit_wallet(member, -delta, "REFUND", reservation_id=rec["id"])
        touch(member)
    rec["billing_status"] = "SETTLED"
    rec["occupancy_status"] = "COMPLETED"
    touch(rec)
    return ok(serialize(rec), 200)


def _cancel_reservation_internal(rec, member):
    """Hold-aware cancellation used directly and by cascades (PRD §3.6)."""
    if rec["billing_status"] == "HOLD_PLACED":
        estimate = rec["estimate_charge_cents"]
        if member is not None:
            credit_wallet(member, estimate, "REFUND", reservation_id=rec["id"])
            member["prepaid_minutes_remaining"] += rec["free_minutes_applied"]
            touch(member)
        rec["free_minutes_applied"] = 0
        rec["billing_status"] = "REFUNDED"
    rec["occupancy_status"] = "CANCELLED"
    touch(rec)


@app.route("/reservations/<id>/cancel", methods=["POST"])
def cancel_reservation(id):
    assert_role_in({"Member"})
    rec = must_find(db.reservations, id)
    assert_member_owns(rec["member_id"])
    if rec["occupancy_status"] not in ("HELD", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409, "Reservation not HELD or CONFIRMED")
    member = db.members.get(rec["member_id"])
    _cancel_reservation_internal(rec, member)
    return ok(serialize(rec), 200)


@app.route("/reservations/<id>/mark-no-show", methods=["POST"])
def mark_no_show(id):
    assert_role_in({"StaffInstructor", "FacilityAdmin"})
    rec = must_find(db.reservations, id)
    if rec["occupancy_status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409, "Reservation not CONFIRMED")
    if not (clock.now >= _parse_iso(rec["end_at"])):
        err("ERR_INVALID_STATE", 409, "Window has not closed")
    # Forfeit hold (PRD §3.6).
    rec["billing_status"] = "SETTLED"
    rec["final_charge_cents"] = rec["estimate_charge_cents"]
    rec["occupancy_status"] = "NO_SHOW"
    touch(rec)
    return ok(serialize(rec), 200)


# ===========================================================================
# LOCKERS (PRD §3.7)
# ===========================================================================
@app.route("/lockers", methods=["POST"])
def create_locker():
    assert_role_in({"Member", "FacilityAdmin"})
    body = get_body()
    member_id = require_str(body, "member_id")
    label = require_str(body, "label")
    capacity = require_int_nonneg(body, "capacity_liters", required=True)
    used = require_int_nonneg(body, "used_liters", default=0)
    # FK existence before OCC (PRD §2.6 ordering: existence < OCC).
    member = must_find(db.members, member_id)
    assert_member_owns(member_id)
    # OCC required (PRD §2.5).
    if "expected_member_version" not in body or body["expected_member_version"] is None:
        err("ERR_INVALID_REQUEST", 422, "Missing required field: expected_member_version")
    expected = body["expected_member_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_INVALID_REQUEST", 422, "expected_member_version must be an integer")
    if member["version"] != expected:
        err("ERR_STALE_VERSION", 412, "Stale member version")

    lid = new_id()
    rec = {
        "id": lid,
        "member_id": member_id,
        "label": label,
        "capacity_liters": capacity,
        "used_liters": used,
        "status": "ASSIGNED",
        "overage_fee_cents": 0,
    }
    rec["overage_fee_cents"] = locker_overage(rec, member)
    stamp_create(rec)
    db.lockers[lid] = rec
    # Assigning a locker bumps Member.version by 1 (scaffold §1.5 side effect).
    touch(member)
    return ok(serialize(rec), 201)


@app.route("/lockers/<id>", methods=["GET"])
def get_locker(id):
    rec = must_find(db.lockers, id)
    return ok(serialize(rec), 200)


@app.route("/lockers", methods=["GET"])
def list_lockers():
    items = list(db.lockers.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [l for l in items if l["member_id"] == member_id]
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@app.route("/lockers/<id>", methods=["PATCH"])
def update_locker(id):
    assert_role_in({"Member"})
    rec = must_find(db.lockers, id)
    assert_member_owns(rec["member_id"])
    body = get_body()
    if "used_liters" in body and body["used_liters"] is not None:
        used = body["used_liters"]
        if isinstance(used, bool) or not isinstance(used, int) or used < 0:
            err("ERR_INVALID_REQUEST", 422, "used_liters must be a non-negative integer")
        rec["used_liters"] = used
    member = db.members.get(rec["member_id"])
    rec["overage_fee_cents"] = locker_overage(rec, member)
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/lockers/<id>/release", methods=["POST"])
def release_locker(id):
    assert_role_in({"Member"})
    rec = must_find(db.lockers, id)
    assert_member_owns(rec["member_id"])
    if rec["status"] != "ASSIGNED":
        err("ERR_INVALID_STATE", 409, "Locker not ASSIGNED")
    member = db.members.get(rec["member_id"])
    rec["overage_fee_cents"] = locker_overage(rec, member)
    if rec["overage_fee_cents"] > 0:
        debit_wallet(member, rec["overage_fee_cents"], "OVERAGE")
        touch(member)
    rec["used_liters"] = 0
    rec["status"] = "RELEASED"
    touch(rec)
    return ok(serialize(rec), 200)


# ===========================================================================
# MATERIAL ITEMS (PRD §3.1)
# ===========================================================================
@app.route("/material-items", methods=["POST"])
def create_material_item():
    assert_role_in({"FacilityAdmin"})
    body = get_body()
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    unit_price = require_int_nonneg(body, "unit_price_cents", required=True)
    stock = require_int_nonneg(body, "stock_qty", default=0)
    for it in db.material_items.values():
        if it["sku"] == sku:
            err("ERR_DUPLICATE_SKU", 409, "Material sku already exists")
    iid = new_id()
    rec = {
        "id": iid,
        "sku": sku,
        "name": name,
        "unit_price_cents": unit_price,
        "stock_qty": stock,
    }
    stamp_create(rec)
    db.material_items[iid] = rec
    return ok(serialize(rec), 201)


@app.route("/material-items/<id>", methods=["GET"])
def get_material_item(id):
    rec = must_find(db.material_items, id)
    return ok(serialize(rec), 200)


@app.route("/material-items", methods=["GET"])
def list_material_items():
    page, meta = paginate(list(db.material_items.values()))
    return ok([serialize(r) for r in page], 200, meta)


# ===========================================================================
# MATERIAL PURCHASES (PRD §3.8)
# ===========================================================================
def _validate_lines(body):
    lines = body.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        err("ERR_INVALID_REQUEST", 422, "lines must be a non-empty array")
    parsed = []
    for line in lines:
        if not isinstance(line, dict):
            err("ERR_INVALID_REQUEST", 422, "each line must be an object")
        item_id = line.get("material_item_id")
        qty = line.get("quantity")
        if not isinstance(item_id, str) or item_id == "":
            err("ERR_INVALID_REQUEST", 422, "line.material_item_id required")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            err("ERR_INVALID_REQUEST", 422, "line.quantity must be >= 1")
        parsed.append({"material_item_id": item_id, "quantity": qty})
    return parsed


@app.route("/material-purchases", methods=["POST"])
def create_material_purchase():
    assert_role_in({"Member"})
    body = get_body()
    member_id = require_str(body, "member_id")
    waste_bps = require_int_nonneg(body, "waste_surcharge_bps", default=0)
    if waste_bps > 10000:
        err("ERR_INVALID_REQUEST", 422, "waste_surcharge_bps must be 0..10000")
    lines = _validate_lines(body)
    member = must_find(db.members, member_id)
    assert_member_owns(member_id)
    # FK resolution: each line's material item (PRD §2.7).
    for line in lines:
        must_find(db.material_items, line["material_item_id"])

    tier = tier_of_member(member)
    subtotal, surcharge, total = material_totals(lines, tier, waste_bps)

    pid = new_id()
    rec = {
        "id": pid,
        "member_id": member_id,
        "lines": lines,
        "waste_surcharge_bps": waste_bps,
        "status": "DRAFT",
        "subtotal_cents": subtotal,
        "surcharge_cents": surcharge,
        "total_cents": total,
    }
    stamp_create(rec)
    db.material_purchases[pid] = rec
    return ok(serialize(rec), 201)


@app.route("/material-purchases/<id>", methods=["GET"])
def get_material_purchase(id):
    rec = must_find(db.material_purchases, id)
    return ok(serialize(rec), 200)


@app.route("/material-purchases", methods=["GET"])
def list_material_purchases():
    items = list(db.material_purchases.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@app.route("/material-purchases/<id>/bill", methods=["POST"])
def bill_material_purchase(id):
    assert_role_in({"Member"})
    rec = must_find(db.material_purchases, id)
    assert_member_owns(rec["member_id"])
    if rec["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Purchase not DRAFT")
    member = db.members.get(rec["member_id"])
    # Stock check (PRD §3.8).
    for line in rec["lines"]:
        item = db.material_items.get(line["material_item_id"])
        if item is None or item["stock_qty"] < line["quantity"]:
            err("ERR_INSUFFICIENT_STOCK", 409, "Insufficient stock")
    tier = tier_of_member(member)
    subtotal, surcharge, total = material_totals(rec["lines"], tier, rec["waste_surcharge_bps"])
    if member["wallet_credit_cents"] < total:
        err("ERR_INSUFFICIENT_FUNDS", 409, "Insufficient funds for purchase")
    rec["subtotal_cents"] = subtotal
    rec["surcharge_cents"] = surcharge
    rec["total_cents"] = total
    # Cascade C: decrement each item stock independently.
    for line in rec["lines"]:
        item = db.material_items[line["material_item_id"]]
        item["stock_qty"] -= line["quantity"]
        touch(item)
    debit_wallet(member, total, "MATERIAL")
    touch(member)
    rec["status"] = "BILLED"
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/material-purchases/<id>/void", methods=["POST"])
def void_material_purchase(id):
    assert_role_in({"Member"})
    rec = must_find(db.material_purchases, id)
    assert_member_owns(rec["member_id"])
    if rec["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Purchase not DRAFT")
    rec["status"] = "VOIDED"
    touch(rec)
    return ok(serialize(rec), 200)


# ===========================================================================
# WORKSHOPS (PRD §3.9)
# ===========================================================================
def _enrolled_count(workshop_id):
    return sum(
        1 for e in db.workshop_enrollments.values()
        if e["workshop_id"] == workshop_id and e["status"] in ("ENROLLED", "ATTENDED")
    )


@app.route("/workshops", methods=["POST"])
def create_workshop():
    assert_role_in({"StaffInstructor", "FacilityAdmin"})
    body = get_body()
    title = require_str(body, "title")
    machine_class = require_enum(body, "machine_class", MACHINE_CLASSES, required=False, default=None)
    instructor_id = require_str(body, "instructor_id")
    starts_at = require_datetime(body, "starts_at")
    capacity = require_int(body, "capacity", required=True)
    if capacity < 1:
        err("ERR_INVALID_REQUEST", 422, "capacity must be >= 1")
    must_find(db.members, instructor_id)

    wid = new_id()
    rec = {
        "id": wid,
        "title": title,
        "machine_class": machine_class,
        "instructor_id": instructor_id,
        "starts_at": _fmt_iso(starts_at),
        "capacity": capacity,
        "status": "OPEN",
        "enrolled_count": 0,
    }
    stamp_create(rec)
    db.workshops[wid] = rec
    return ok(serialize(rec), 201)


@app.route("/workshops/<id>", methods=["GET"])
def get_workshop(id):
    rec = must_find(db.workshops, id)
    rec["enrolled_count"] = _enrolled_count(rec["id"])
    return ok(serialize(rec), 200)


@app.route("/workshops", methods=["GET"])
def list_workshops():
    items = list(db.workshops.values())
    instructor_id = request.args.get("instructor_id")
    machine_class = request.args.get("machine_class")
    if instructor_id is not None:
        items = [w for w in items if w["instructor_id"] == instructor_id]
    if machine_class is not None:
        items = [w for w in items if w["machine_class"] == machine_class]
    for w in items:
        w["enrolled_count"] = _enrolled_count(w["id"])
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@app.route("/workshops/<id>/start", methods=["POST"])
def start_workshop(id):
    assert_role_in({"StaffInstructor"})
    rec = must_find(db.workshops, id)
    if rec["status"] not in ("OPEN", "FULL"):
        err("ERR_INVALID_STATE", 409, "Workshop not OPEN or FULL")
    if not (clock.now >= _parse_iso(rec["starts_at"])):
        err("ERR_INVALID_STATE", 409, "Workshop start time not reached")
    rec["status"] = "RUNNING"
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/workshops/<id>/complete", methods=["POST"])
def complete_workshop(id):
    assert_role_in({"StaffInstructor"})
    rec = must_find(db.workshops, id)
    if rec["status"] != "RUNNING":
        err("ERR_INVALID_STATE", 409, "Workshop not RUNNING")
    rec["status"] = "COMPLETED"
    touch(rec)
    # Cascade D step 1: ENROLLED -> NO_SHOW.
    for e in list(db.workshop_enrollments.values()):
        if e["workshop_id"] == rec["id"] and e["status"] == "ENROLLED":
            e["status"] = "NO_SHOW"
            touch(e)
    rec["enrolled_count"] = _enrolled_count(rec["id"])
    return ok(serialize(rec), 200)


@app.route("/workshops/<id>/cancel", methods=["POST"])
def cancel_workshop(id):
    assert_role_in({"StaffInstructor", "FacilityAdmin"})
    rec = must_find(db.workshops, id)
    if rec["status"] not in ("OPEN", "FULL"):
        err("ERR_INVALID_STATE", 409, "Workshop not OPEN or FULL")
    rec["status"] = "CANCELLED"
    touch(rec)
    # Cascade: ENROLLED -> WITHDRAWN.
    for e in list(db.workshop_enrollments.values()):
        if e["workshop_id"] == rec["id"] and e["status"] == "ENROLLED":
            e["status"] = "WITHDRAWN"
            touch(e)
    rec["enrolled_count"] = _enrolled_count(rec["id"])
    return ok(serialize(rec), 200)


# ===========================================================================
# WORKSHOP ENROLLMENTS (PRD §3.9)
# ===========================================================================
@app.route("/workshop-enrollments", methods=["POST"])
def create_enrollment():
    assert_role_in({"Member"})
    body = get_body()
    workshop_id = require_str(body, "workshop_id")
    member_id = require_str(body, "member_id")
    workshop = must_find(db.workshops, workshop_id)
    member = must_find(db.members, member_id)
    assert_member_owns(member_id)

    # Duplicate non-terminal enrollment (PRD §2.10).
    for e in db.workshop_enrollments.values():
        if (e["workshop_id"] == workshop_id and e["member_id"] == member_id
                and e["status"] == "ENROLLED"):
            err("ERR_DUPLICATE_ENROLLMENT", 409, "Member already enrolled")

    # Seat check (PRD §3.9).
    count = _enrolled_count(workshop_id)
    if count >= workshop["capacity"]:
        err("ERR_WORKSHOP_FULL", 409, "Workshop is full")

    eid = new_id()
    rec = {
        "id": eid,
        "workshop_id": workshop_id,
        "member_id": member_id,
        "status": "ENROLLED",
        "certification_id": None,
    }
    stamp_create(rec)
    db.workshop_enrollments[eid] = rec

    new_count = _enrolled_count(workshop_id)
    workshop["enrolled_count"] = new_count
    if workshop["status"] == "OPEN" and new_count >= workshop["capacity"]:
        workshop["status"] = "FULL"
    touch(workshop)
    return ok(serialize(rec), 201)


@app.route("/workshop-enrollments/<id>", methods=["GET"])
def get_enrollment(id):
    rec = must_find(db.workshop_enrollments, id)
    return ok(serialize(rec), 200)


@app.route("/workshop-enrollments", methods=["GET"])
def list_enrollments():
    items = list(db.workshop_enrollments.values())
    for key in ("workshop_id", "member_id", "certification_id"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], 200, meta)


@app.route("/workshop-enrollments/<id>/mark-attended", methods=["POST"])
def mark_attended(id):
    assert_role_in({"StaffInstructor"})
    rec = must_find(db.workshop_enrollments, id)
    if rec["status"] != "ENROLLED":
        err("ERR_INVALID_STATE", 409, "Enrollment not ENROLLED")
    workshop = db.workshops.get(rec["workshop_id"])
    if workshop["status"] != "RUNNING":
        err("ERR_INVALID_STATE", 409, "Workshop not RUNNING")
    rec["status"] = "ATTENDED"
    if workshop["machine_class"] is not None:
        cert = _mint_certification(
            rec["member_id"], workshop["machine_class"],
            orientation_complete=True, supervised_minutes=0,
            required_supervised_minutes=0)
        rec["certification_id"] = cert["id"]
    touch(rec)
    workshop["enrolled_count"] = _enrolled_count(workshop["id"])
    return ok(serialize(rec), 200)


@app.route("/workshop-enrollments/<id>/mark-no-show", methods=["POST"])
def enrollment_no_show(id):
    assert_role_in({"StaffInstructor"})
    rec = must_find(db.workshop_enrollments, id)
    if rec["status"] != "ENROLLED":
        err("ERR_INVALID_STATE", 409, "Enrollment not ENROLLED")
    rec["status"] = "NO_SHOW"
    touch(rec)
    workshop = db.workshops.get(rec["workshop_id"])
    if workshop:
        workshop["enrolled_count"] = _enrolled_count(workshop["id"])
    return ok(serialize(rec), 200)


@app.route("/workshop-enrollments/<id>/withdraw", methods=["POST"])
def withdraw_enrollment(id):
    assert_role_in({"Member"})
    rec = must_find(db.workshop_enrollments, id)
    assert_member_owns(rec["member_id"])
    if rec["status"] != "ENROLLED":
        err("ERR_INVALID_STATE", 409, "Enrollment not ENROLLED")
    workshop = db.workshops.get(rec["workshop_id"])
    if workshop["status"] not in ("OPEN", "FULL"):
        err("ERR_INVALID_STATE", 409, "Workshop not OPEN or FULL")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    new_count = _enrolled_count(workshop["id"])
    workshop["enrolled_count"] = new_count
    if workshop["status"] == "FULL" and new_count < workshop["capacity"]:
        workshop["status"] = "OPEN"
    touch(workshop)
    return ok(serialize(rec), 200)


# ===========================================================================
# Entrypoint
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
