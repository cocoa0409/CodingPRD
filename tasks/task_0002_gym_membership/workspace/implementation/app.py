"""Gym Membership Management API — Flask application entry point."""
import os
import re
import hashlib
from datetime import timedelta
from decimal import Decimal
from flask import Flask, request

import db
from common import (
    ApiError, CLOCK, gen_uuid, iso_now, format_iso, parse_iso,
    success_object, success_array, error_response, round_half_up_to_int,
)
from auth import get_auth, require_role, VALID_ROLES
from constants import (
    PLAN_PRICE_CENTS, TIER_RANK,
    CONFIRM_CUTOFF_MINUTES, MIN_LEAD_MINUTES, TRAINER_BUFFER_MINUTES,
    CHECK_IN_PREWINDOW_MINUTES, RETRY_LIMIT, PAYMENT_IN_FLIGHT_SECONDS,
    NO_SHOW_PENALTY_CENTS, NO_SHOW_STRIKE_LIMIT, STRIKE_SUSPENSION_DAYS,
    grace_period_days, late_fee_pct, max_suspension_days, refund_schedule,
    REFERRAL_REWARD_CENTS_BY_PLAN,
)
from calculations import (
    booking_provisional_price, subscription_charge_amount,
    compute_account_posture, plan_base_price,
)
from serializers import (
    serialize_member, serialize_subscription, serialize_payment_attempt,
    serialize_store, serialize_class_session, serialize_trainer,
    serialize_equipment_pool, serialize_booking, serialize_coupon,
    serialize_referral, serialize_wallet,
)
import services
from services import (
    bump, recompute_posture, coupon_set_status_if_needed,
    coupon_validate_redeemable, coupon_increment, coupon_decrement,
    member_set_suspended, member_clear_suspension, member_cascade_to_active,
    member_cascade_to_frozen, member_wallet_ledger_append,
    cancel_booking_member, promote_waitlist, process_payment_attempt,
    clock_advance_cascades, sweep_run,
)


app = Flask(__name__)
app.url_map.strict_slashes = False


# ----------------------------- error handlers -------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_INVALID_REQUEST", 400, "Path not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", 400, "Method not allowed")


@app.errorhandler(400)
def handle_400(e):
    return error_response("ERR_INVALID_REQUEST", 400, "Bad request")


@app.errorhandler(Exception)
def handle_unexpected(e):
    import traceback
    traceback.print_exc()
    return error_response("ERR_INVALID_REQUEST", 400, f"Server error: {e}")


# ----------------------------- request helpers ------------------------------
def body():
    try:
        data = request.get_json(silent=True, force=True)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field '{f}'")


def as_str(data, key, *, required=True, allow_none=False):
    v = data.get(key)
    if v is None:
        if required and not allow_none:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field '{key}'")
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{key}' must be string")
    return v


def as_int(data, key, *, required=True, allow_none=False, default=None):
    if key not in data or data[key] is None:
        if required and not allow_none:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field '{key}'")
        return default
    v = data[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{key}' must be integer")
    return v


def as_bool(data, key, *, required=False, default=None):
    if key not in data or data[key] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field '{key}'")
        return default
    v = data[key]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{key}' must be boolean")
    return v


def as_iso(data, key, *, required=True, allow_none=False):
    v = data.get(key)
    if v is None:
        if required and not allow_none:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field '{key}'")
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{key}' must be ISO 8601 string")
    try:
        return parse_iso(v)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{key}' is not a valid ISO 8601 instant")


def get_pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate_list(items, limit, offset):
    total = len(items)
    page = items[offset: offset + limit]
    return page, total


# ----------------------------- existence helpers ----------------------------
def require_member(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, f"Member {member_id} not found")
    return m


def require_subscription(member_id, sub_id):
    require_member(member_id)
    sub = db.subscriptions.get(sub_id)
    if sub is None or sub["member_id"] != member_id:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, f"Subscription {sub_id} not found")
    return sub


def require_booking(member_id, booking_id):
    require_member(member_id)
    b = db.bookings.get(booking_id)
    if b is None or b["member_id"] != member_id:
        raise ApiError("ERR_BOOKING_NOT_FOUND", 404, f"Booking {booking_id} not found")
    return b


def require_store(store_id):
    s = db.stores.get(store_id)
    if s is None:
        raise ApiError("ERR_STORE_NOT_FOUND", 404, f"Store {store_id} not found")
    return s


def require_class_session(store_id, session_id):
    require_store(store_id)
    cs = db.class_sessions.get(session_id)
    if cs is None or cs["store_id"] != store_id:
        raise ApiError("ERR_CLASS_SESSION_NOT_FOUND", 404, f"ClassSession {session_id} not found")
    return cs


def require_trainer(trainer_id):
    t = db.trainers.get(trainer_id)
    if t is None:
        raise ApiError("ERR_TRAINER_NOT_FOUND", 404, f"Trainer {trainer_id} not found")
    return t


def require_coupon(coupon_id):
    c = db.coupons.get(coupon_id)
    if c is None:
        raise ApiError("ERR_COUPON_NOT_FOUND", 404, f"Coupon {coupon_id} not found")
    coupon_set_status_if_needed(c)
    return c


def require_equipment_pool(store_id, pool_id):
    require_store(store_id)
    ep = db.equipment_pools.get(pool_id)
    if ep is None or ep["store_id"] != store_id:
        raise ApiError("ERR_EQUIPMENT_POOL_NOT_FOUND", 404, f"EquipmentPool {pool_id} not found")
    return ep


# ----------------------------- ownership helpers ----------------------------
def check_member_ownership(member_id, user_id, role):
    """Members can only access their own resources via /members/{memberId}/..."""
    if role == "Member" and member_id != user_id:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "Member can only access own resources")


def check_occ(entity, body_data):
    """Optimistic concurrency: if 'version' supplied in body, compare to stored."""
    if body_data and "version" in body_data and body_data["version"] is not None:
        if body_data["version"] != entity.get("version"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           f"OCC mismatch: expected version {entity.get('version')}, got {body_data['version']}")


# ============================================================================
# Members & registration
# ============================================================================
EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")
COUPON_CODE_RE = re.compile(r"^[A-Z0-9]{6,12}$")


def _hash_password(pw: str) -> str:
    # Argon2id ideally; we use a cheap deterministic hash for now (no real auth).
    return hashlib.sha256(("gymsalt::" + pw).encode("utf-8")).hexdigest()


@app.route("/members", methods=["POST"])
def create_member():
    user_id, role = require_role({"Any", "Member", "BillingAdmin", "StoreManager", "Trainer"})
    data = body()
    require_fields(data, ["email", "password", "home_store_id", "state_code"])
    email = as_str(data, "email").lower()
    password = as_str(data, "password")
    home_store_id = as_str(data, "home_store_id")
    state_code = as_str(data, "state_code")
    referred_by = as_str(data, "referred_by_member_id", required=False)
    plan = as_str(data, "plan", required=False)
    billing_cycle = as_str(data, "billing_cycle", required=False)
    applied_coupon_code = as_str(data, "applied_coupon_code", required=False)

    if not EMAIL_RE.match(email):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid email format")
    if not STATE_RE.match(state_code):
        raise ApiError("ERR_INVALID_REQUEST", 400, "state_code must be 2 uppercase letters")
    # Email uniqueness
    if any(m["email"] == email for m in db.members.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Email already registered")
    # Home store existence
    if home_store_id not in db.stores:
        raise ApiError("ERR_STORE_NOT_FOUND", 404, f"Home store {home_store_id} not found")

    # Self-referral check: priority 15 — only meaningful if referred_by resolves
    # to a real existing member who is this newly registering email.
    if referred_by is not None:
        if referred_by not in db.members:
            # The PRD names ERR_REFERRAL_NOT_FOUND for "sponsor-referral lookups"
            raise ApiError("ERR_REFERRAL_NOT_FOUND", 404, f"Referrer {referred_by} not found")
        sponsor = db.members[referred_by]
        if sponsor["email"] == email:
            raise ApiError("ERR_SELF_REFERRAL", 400, "Cannot refer self")

    now = CLOCK.now()
    member_id = gen_uuid()
    # tier is set from plan when subscription activates; default BASIC at start
    member = {
        "id": member_id,
        "email": email,
        "password_hash": _hash_password(password),
        "home_store_id": home_store_id,
        "tier": (plan if plan in ("BASIC", "PLUS", "ELITE") else "BASIC"),
        "state_code": state_code,
        "billing_status": "CURRENT",
        "access_status": "ACTIVE",
        "account_posture": "OPEN",
        "no_show_strike_count": 0,
        "wallet_credit_cents": 0,
        "suspension_window_start": None,
        "suspension_window_end": None,
        "referred_by_member_id": referred_by,
        "wallet_ledger": [],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    member["account_posture"] = compute_account_posture(member["billing_status"], member["access_status"])
    db.members[member_id] = member

    # Create referral row if applicable
    if referred_by is not None:
        rid = gen_uuid()
        db.referrals[rid] = {
            "id": rid,
            "sponsor_member_id": referred_by,
            "invitee_member_id": member_id,
            "minted_coupon_id": None,
            "status": "PENDING",
            "qualifying_attempt_id": None,
            "reward_value_cents": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }

    # Optional bootstrap subscription
    if plan is not None and billing_cycle is not None:
        if plan not in ("BASIC", "PLUS", "ELITE"):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid plan")
        if billing_cycle not in ("MONTHLY", "ANNUAL"):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid billing_cycle")
        coupon = None
        if applied_coupon_code is not None:
            coupon = next((c for c in db.coupons.values() if c["code"] == applied_coupon_code), None)
            if coupon is None:
                raise ApiError("ERR_COUPON_NOT_FOUND", 404, "Coupon code not found")
            coupon_validate_redeemable(coupon, "SUBSCRIPTION", member=member)
        sub_id = gen_uuid()
        sub = {
            "id": sub_id,
            "member_id": member_id,
            "plan": plan,
            "billing_cycle": billing_cycle,
            "base_price_cents": plan_base_price(plan, billing_cycle),
            "status": "PENDING_ACTIVATION",
            "current_period_start": None,
            "current_period_end": None,
            "auto_renew": True,
            "failed_payment_attempts": 0,
            "grace_period_end": None,
            "cancellation_effective_at": None,
            "applied_coupon_id": coupon["id"] if coupon else None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.subscriptions[sub_id] = sub

    return success_object(serialize_member(member), 201)


@app.route("/members/<member_id>/login", methods=["POST"])
def login(member_id):
    user_id, role = require_role({"Any", "Member", "BillingAdmin", "StoreManager", "Trainer"})
    member = require_member(member_id)
    data = body()
    require_fields(data, ["email", "password"])
    email = as_str(data, "email").lower()
    pw = as_str(data, "password")
    if member["email"] != email or member["password_hash"] != _hash_password(pw):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid credentials")
    return success_object(serialize_member(member), 200)


@app.route("/members", methods=["GET"])
def list_members():
    require_role({"StoreManager", "BillingAdmin"})
    limit, offset = get_pagination()
    tier = request.args.get("tier")
    billing_status = request.args.get("billing_status")
    items = list(db.members.values())
    if tier:
        items = [m for m in items if m["tier"] == tier]
    if billing_status:
        items = [m for m in items if m["billing_status"] == billing_status]
    items.sort(key=lambda m: m["created_at"])
    page, total = paginate_list(items, limit, offset)
    return success_array([serialize_member(m) for m in page], limit, offset, total)


@app.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    user_id, role = require_role({"Member", "Trainer", "StoreManager", "BillingAdmin"})
    member = require_member(member_id)
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    elif role == "Trainer":
        # Only allowed to view members in their sessions
        trainer = db.trainers.get(user_id)
        if trainer is None:
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "Trainer not found")
        leads = any(
            b["member_id"] == member_id and (
                (b.get("trainer_id") == user_id) or
                (b.get("class_session_id") and db.class_sessions.get(b["class_session_id"], {}).get("trainer_id") == user_id)
            )
            for b in db.bookings.values()
        )
        if not leads:
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "Trainer can only view own session members")
    return success_object(serialize_member(member))


# ----- suspend / resume / cancel -------------------------------------------
@app.route("/members/<member_id>/suspend", methods=["POST"])
def suspend_member(member_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    member = require_member(member_id)
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    data = body()
    check_occ(member, data)
    requested_days = as_int(data, "requested_days", required=False, allow_none=True, default=None)

    if member["access_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, f"Cannot suspend from access_status={member['access_status']}")
    # Subscription precondition (PRD §3.4): "Suspension is only permitted when
    # the member's Subscription.status is in ACTIVE or REINSTATED ... if either
    # condition fails, the request is rejected with ERR_HAS_FUTURE_BOOKINGS."
    subs = [s for s in db.subscriptions.values() if s["member_id"] == member_id]
    active_sub = next((s for s in subs if s["status"] in ("ACTIVE", "REINSTATED")), None)
    if active_sub is None:
        raise ApiError("ERR_HAS_FUTURE_BOOKINGS", 409, "Subscription not ACTIVE/REINSTATED")

    # Compute window
    cap_days = max_suspension_days(member["state_code"])
    if requested_days is not None and requested_days > 0:
        duration_days = min(cap_days, requested_days)
    else:
        duration_days = cap_days
    suspension_end = CLOCK.now() + timedelta(days=duration_days)

    # Future booking check (RESERVED or CONFIRMED in window)
    for b in db.bookings.values():
        if b["member_id"] != member_id:
            continue
        if b["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        if b["starts_at"] > CLOCK.now() and b["starts_at"] <= suspension_end:
            raise ApiError("ERR_HAS_FUTURE_BOOKINGS", 409, "Future bookings exist in suspension window")

    member_set_suspended(member, duration_days)
    return success_object(serialize_member(member))


@app.route("/members/<member_id>/resume", methods=["POST"])
def resume_member(member_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    member = require_member(member_id)
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    data = body()
    check_occ(member, data)
    if member["access_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, f"Cannot resume from access_status={member['access_status']}")
    member_clear_suspension(member)
    return success_object(serialize_member(member))


@app.route("/members/<member_id>/cancel", methods=["POST"])
def cancel_member(member_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    member = require_member(member_id)
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    data = body()
    check_occ(member, data)
    if member["access_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Already cancelled")
    # Payment-in-flight: any payment attempt in last 2 minutes that is "in-flight"?
    # We treat non-SUCCESS very recent attempts as in-flight only when they're not SUCCESS/FAILED/DECLINED.
    # Since all outcomes here are terminal, we only block if there's a brand-new attempt within 2 min.
    # Interpreted as: any payment attempt within last 2 minutes whose outcome is not terminal.
    # Our outcomes are all terminal (SUCCESS/FAILED/DECLINED), so effectively we just check there's no
    # PaymentAttempt created in last PAYMENT_IN_FLIGHT_SECONDS with outcome marked as in-flight.
    # For safety, block when an attempt was created within 2 min that is not SUCCESS.
    now = CLOCK.now()
    cutoff = now - timedelta(seconds=PAYMENT_IN_FLIGHT_SECONDS)
    for pa in db.payment_attempts.values():
        if pa["member_id"] != member_id:
            continue
        if pa["created_at"] >= cutoff and pa["outcome"] not in ("SUCCESS", "FAILED", "DECLINED"):
            raise ApiError("ERR_PAYMENT_IN_FLIGHT", 409, "Payment attempt in flight")

    # Set subscription(s) cancellation effective at current_period_end
    for sub in db.subscriptions.values():
        if sub["member_id"] != member_id:
            continue
        if sub["status"] in ("ACTIVE", "PAST_DUE", "GRACE", "DELINQUENT", "REINSTATED"):
            sub["cancellation_effective_at"] = sub.get("current_period_end") or CLOCK.now()
            sub["auto_renew"] = False
            bump(sub)
    member["access_status"] = "FROZEN"
    recompute_posture(member)
    bump(member)
    return success_object(serialize_member(member))


# ============================================================================
# Subscriptions
# ============================================================================
@app.route("/members/<member_id>/subscriptions", methods=["POST"])
def create_subscription(member_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    member = require_member(member_id)
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    data = body()
    require_fields(data, ["plan", "billing_cycle"])
    plan = as_str(data, "plan")
    billing_cycle = as_str(data, "billing_cycle")
    auto_renew = as_bool(data, "auto_renew", default=True)
    applied_coupon_code = as_str(data, "applied_coupon_code", required=False)

    if plan not in ("BASIC", "PLUS", "ELITE"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid plan")
    if billing_cycle not in ("MONTHLY", "ANNUAL"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid billing_cycle")

    coupon = None
    if applied_coupon_code is not None:
        coupon = next((c for c in db.coupons.values() if c["code"] == applied_coupon_code), None)
        if coupon is None:
            raise ApiError("ERR_COUPON_NOT_FOUND", 404, "Coupon code not found")
        coupon_validate_redeemable(coupon, "SUBSCRIPTION", member=member)

    now = CLOCK.now()
    sub_id = gen_uuid()
    sub = {
        "id": sub_id,
        "member_id": member_id,
        "plan": plan,
        "billing_cycle": billing_cycle,
        "base_price_cents": plan_base_price(plan, billing_cycle),
        "status": "PENDING_ACTIVATION",
        "current_period_start": None,
        "current_period_end": None,
        "auto_renew": auto_renew,
        "failed_payment_attempts": 0,
        "grace_period_end": None,
        "cancellation_effective_at": None,
        "applied_coupon_id": coupon["id"] if coupon else None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.subscriptions[sub_id] = sub
    return success_object(serialize_subscription(sub), 201)


@app.route("/members/<member_id>/subscriptions", methods=["GET"])
def list_subscriptions(member_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    require_member(member_id)
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    limit, offset = get_pagination()
    items = [s for s in db.subscriptions.values() if s["member_id"] == member_id]
    items.sort(key=lambda s: s["created_at"])
    page, total = paginate_list(items, limit, offset)
    return success_array([serialize_subscription(s) for s in page], limit, offset, total)


@app.route("/members/<member_id>/subscriptions/<sub_id>", methods=["GET"])
def get_subscription(member_id, sub_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    sub = require_subscription(member_id, sub_id)
    return success_object(serialize_subscription(sub))


@app.route("/members/<member_id>/subscriptions/<sub_id>/reinstate", methods=["POST"])
def reinstate_subscription(member_id, sub_id):
    require_role({"BillingAdmin"})
    member = require_member(member_id)
    sub = require_subscription(member_id, sub_id)
    data = body()
    check_occ(sub, data)
    if sub["status"] != "DELINQUENT":
        raise ApiError("ERR_INVALID_STATE", 409, f"Cannot reinstate from status={sub['status']}")
    # Require recent SUCCESS PaymentAttempt
    has_success = any(
        pa["subscription_id"] == sub_id and pa["outcome"] == "SUCCESS"
        for pa in db.payment_attempts.values()
    )
    if not has_success:
        raise ApiError("ERR_INVALID_STATE", 409, "No SUCCESS payment attempt found")
    sub["status"] = "ACTIVE"
    sub["failed_payment_attempts"] = 0
    sub["grace_period_end"] = None
    bump(sub)
    member["billing_status"] = "CURRENT"
    member_cascade_to_active(member)
    return success_object(serialize_subscription(sub))


# ============================================================================
# Payment Attempts
# ============================================================================
@app.route("/members/<member_id>/subscriptions/<sub_id>/payment-attempts", methods=["POST"])
def create_payment_attempt(member_id, sub_id):
    user_id, role = require_role({"BillingAdmin"})
    member = require_member(member_id)
    sub = require_subscription(member_id, sub_id)
    data = body()
    require_fields(data, ["gateway_txn_id", "idempotency_key", "outcome"])
    gateway_txn_id = as_str(data, "gateway_txn_id")
    idempotency_key = as_str(data, "idempotency_key")
    outcome = as_str(data, "outcome")
    failure_reason = as_str(data, "failure_reason", required=False, allow_none=True)
    client_amount = as_int(data, "amount_cents", required=False, allow_none=True, default=None)

    if outcome not in ("SUCCESS", "FAILED", "DECLINED"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid outcome")

    # Idempotency replay: per subscription
    for pa in db.payment_attempts.values():
        if pa["subscription_id"] == sub_id and pa["idempotency_key"] == idempotency_key:
            return error_response("ERR_IDEMPOTENT_REPLAY", 200, "Replay of prior payment attempt")

    # State: cannot create attempt on CANCELLED
    if sub["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription cancelled")

    # Period rollover: PRD §3.2 — "When the logical clock advances past
    # current_period_end, the server enqueues a new payment attempt for the
    # next period." If the current attempt is being submitted after the
    # previous period_end (and the subscription is ACTIVE), roll the period
    # forward so this attempt is recognised as attempt_number=1 of the new period.
    if (sub["status"] == "ACTIVE"
            and sub.get("current_period_end")
            and CLOCK.now() > sub["current_period_end"]):
        from services import _add_cycle
        sub["current_period_start"] = sub["current_period_end"]
        sub["current_period_end"] = _add_cycle(sub["current_period_start"], sub["billing_cycle"])
        sub["failed_payment_attempts"] = 0
        bump(sub)

    # Compute attempt_number
    # If this is the first attempt of the current period -> 1, else increment
    # Period boundary is current_period_start; for PENDING_ACTIVATION there is none yet so attempts start at 1.
    period_start = sub.get("current_period_start")
    period_attempts = []
    for pa in db.payment_attempts.values():
        if pa["subscription_id"] != sub_id:
            continue
        if period_start is None:
            period_attempts.append(pa)
        elif pa["created_at"] >= period_start:
            period_attempts.append(pa)
    attempt_number = len(period_attempts) + 1

    # Server-recompute expected amount_cents
    coupon = db.coupons.get(sub.get("applied_coupon_id")) if sub.get("applied_coupon_id") else None
    expected_amount, _wallet_applied, _discount = subscription_charge_amount(sub, member, coupon)

    # For retry attempts (>1), expected amount is the SAME amount that attempt 1 computed.
    if attempt_number > 1:
        # Find attempt 1 of this period
        first = next((pa for pa in period_attempts if pa["attempt_number"] == 1), None)
        if first is not None:
            expected_amount = first["amount_cents"]

    if client_amount is not None and client_amount != expected_amount:
        raise ApiError("ERR_AMOUNT_MISMATCH", 422,
                       f"Amount mismatch: expected {expected_amount}, got {client_amount}")

    attempt_id = gen_uuid()
    pa = process_payment_attempt(
        member=member,
        subscription=sub,
        outcome=outcome,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        amount_cents=expected_amount,
        gateway_txn_id=gateway_txn_id,
        idempotency_key=idempotency_key,
        failure_reason=failure_reason,
    )
    return success_object(serialize_payment_attempt(pa), 201)


@app.route("/members/<member_id>/subscriptions/<sub_id>/payment-attempts", methods=["GET"])
def list_payment_attempts(member_id, sub_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    require_subscription(member_id, sub_id)
    limit, offset = get_pagination()
    items = [pa for pa in db.payment_attempts.values() if pa["subscription_id"] == sub_id]
    items.sort(key=lambda p: p["created_at"])
    page, total = paginate_list(items, limit, offset)
    return success_array([serialize_payment_attempt(p) for p in page], limit, offset, total)


# ============================================================================
# Stores
# ============================================================================
@app.route("/stores", methods=["POST"])
def create_store():
    # Not exposed in PRD endpoint table — bootstrap-only via BillingAdmin
    require_role({"BillingAdmin", "StoreManager"})
    data = body()
    require_fields(data, ["name", "state_code", "opens_at_local", "closes_at_local", "gate_device_id"])
    now = CLOCK.now()
    sid = gen_uuid()
    s = {
        "id": sid,
        "name": as_str(data, "name"),
        "state_code": as_str(data, "state_code"),
        "opens_at_local": as_str(data, "opens_at_local"),
        "closes_at_local": as_str(data, "closes_at_local"),
        "gate_device_id": as_str(data, "gate_device_id"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.stores[sid] = s
    return success_object(serialize_store(s), 201)


@app.route("/stores", methods=["GET"])
def list_stores():
    require_role(VALID_ROLES)
    limit, offset = get_pagination()
    state_code = request.args.get("state_code")
    items = list(db.stores.values())
    if state_code:
        items = [s for s in items if s["state_code"] == state_code]
    items.sort(key=lambda s: s["created_at"])
    page, total = paginate_list(items, limit, offset)
    return success_array([serialize_store(s) for s in page], limit, offset, total)


@app.route("/stores/<store_id>", methods=["GET"])
def get_store(store_id):
    require_role(VALID_ROLES)
    s = require_store(store_id)
    return success_object(serialize_store(s))


# ----- ClassSessions --------------------------------------------------------
@app.route("/stores/<store_id>/class-sessions", methods=["POST"])
def create_class_session(store_id):
    require_role({"StoreManager"})
    store = require_store(store_id)
    data = body()
    require_fields(data, ["class_type", "trainer_id", "starts_at", "ends_at", "capacity"])
    class_type = as_str(data, "class_type")
    trainer_id = as_str(data, "trainer_id")
    starts_at = as_iso(data, "starts_at")
    ends_at = as_iso(data, "ends_at")
    capacity = as_int(data, "capacity")
    minimum_tier = as_str(data, "minimum_tier", required=False) or "BASIC"
    equipment_pool_id = as_str(data, "equipment_pool_id", required=False, allow_none=True)
    equipment_units_required = as_int(data, "equipment_units_required", required=False, allow_none=True, default=0) or 0

    if ends_at <= starts_at:
        raise ApiError("ERR_INVALID_REQUEST", 400, "ends_at must be greater than starts_at")
    if capacity < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "capacity must be >= 1")
    if minimum_tier not in ("BASIC", "PLUS", "ELITE"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid minimum_tier")
    # Trainer existence
    require_trainer(trainer_id)
    # Equipment pool validation
    if equipment_pool_id is not None:
        pool = require_equipment_pool(store_id, equipment_pool_id)
        # Maintenance window check
        mws = pool.get("maintenance_window_start")
        mwe = pool.get("maintenance_window_end")
        if mws and mwe:
            if not (ends_at <= mws or starts_at >= mwe):
                raise ApiError("ERR_EQUIPMENT_UNAVAILABLE", 409, "Window overlaps maintenance")
        # Capacity check
        overlapping_units = 0
        for cs in db.class_sessions.values():
            if cs.get("equipment_pool_id") != equipment_pool_id:
                continue
            if cs["status"] not in ("SCHEDULED", "LOCKED"):
                continue
            if cs["ends_at"] <= starts_at or cs["starts_at"] >= ends_at:
                continue
            overlapping_units += cs.get("equipment_units_required", 0)
        if overlapping_units + equipment_units_required > pool["total_units"]:
            raise ApiError("ERR_EQUIPMENT_UNAVAILABLE", 409, "Insufficient equipment units")

    now = CLOCK.now()
    csid = gen_uuid()
    cs = {
        "id": csid,
        "store_id": store_id,
        "class_type": class_type,
        "trainer_id": trainer_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "minimum_tier": minimum_tier,
        "equipment_pool_id": equipment_pool_id,
        "equipment_units_required": equipment_units_required,
        "reserved_seat_count": 0,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.class_sessions[csid] = cs
    return success_object(serialize_class_session(cs), 201)


@app.route("/stores/<store_id>/class-sessions", methods=["GET"])
def list_class_sessions(store_id):
    require_role(VALID_ROLES)
    require_store(store_id)
    limit, offset = get_pagination()
    fro = request.args.get("from")
    to = request.args.get("to")
    items = [cs for cs in db.class_sessions.values() if cs["store_id"] == store_id]
    if fro:
        fro_dt = parse_iso(fro)
        items = [cs for cs in items if cs["starts_at"] >= fro_dt]
    if to:
        to_dt = parse_iso(to)
        items = [cs for cs in items if cs["starts_at"] < to_dt]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate_list(items, limit, offset)
    return success_array([serialize_class_session(c) for c in page], limit, offset, total)


@app.route("/stores/<store_id>/class-sessions/<session_id>", methods=["GET"])
def get_class_session(store_id, session_id):
    require_role(VALID_ROLES)
    cs = require_class_session(store_id, session_id)
    return success_object(serialize_class_session(cs))


@app.route("/stores/<store_id>/class-sessions/<session_id>/cancel", methods=["POST"])
def cancel_class_session(store_id, session_id):
    require_role({"StoreManager"})
    cs = require_class_session(store_id, session_id)
    data = body()
    check_occ(cs, data)
    if cs["status"] not in ("SCHEDULED", "LOCKED"):
        raise ApiError("ERR_INVALID_STATE", 409, f"Cannot cancel from status={cs['status']}")
    cs["status"] = "CANCELLED"
    bump(cs)
    # Cascade-cancel all non-terminal bookings with ADMIN refund
    for b in list(db.bookings.values()):
        if b.get("class_session_id") != session_id:
            continue
        if b["status"] in ("ATTENDED", "NO_SHOW", "CANCELLED"):
            continue
        owner = db.members.get(b["member_id"])
        if owner is None:
            continue
        services._cancel_booking_admin(b, owner, reason="session_cancelled")
    return success_object(serialize_class_session(cs))


# ----- EquipmentPools -------------------------------------------------------
@app.route("/stores/<store_id>/equipment-pools", methods=["POST"])
def create_equipment_pool(store_id):
    require_role({"StoreManager"})
    require_store(store_id)
    data = body()
    require_fields(data, ["equipment_type", "total_units"])
    equipment_type = as_str(data, "equipment_type")
    total_units = as_int(data, "total_units")
    mws = as_iso(data, "maintenance_window_start", required=False, allow_none=True)
    mwe = as_iso(data, "maintenance_window_end", required=False, allow_none=True)
    if total_units < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "total_units must be >= 1")
    if (mws is None) ^ (mwe is None):
        raise ApiError("ERR_INVALID_REQUEST", 400, "maintenance_window_start and _end must both be provided or both null")
    if mws and mwe and mwe <= mws:
        raise ApiError("ERR_INVALID_REQUEST", 400, "maintenance_window_end must be > start")
    now = CLOCK.now()
    pid = gen_uuid()
    ep = {
        "id": pid,
        "store_id": store_id,
        "equipment_type": equipment_type,
        "total_units": total_units,
        "maintenance_window_start": mws,
        "maintenance_window_end": mwe,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.equipment_pools[pid] = ep
    return success_object(serialize_equipment_pool(ep), 201)


@app.route("/stores/<store_id>/equipment-pools", methods=["GET"])
def list_equipment_pools(store_id):
    require_role(VALID_ROLES)
    require_store(store_id)
    limit, offset = get_pagination()
    items = [ep for ep in db.equipment_pools.values() if ep["store_id"] == store_id]
    items.sort(key=lambda e: e["created_at"])
    page, total = paginate_list(items, limit, offset)
    return success_array([serialize_equipment_pool(e) for e in page], limit, offset, total)


# ============================================================================
# Trainers
# ============================================================================
@app.route("/trainers", methods=["POST"])
def create_trainer():
    require_role({"StoreManager", "BillingAdmin"})
    data = body()
    require_fields(data, ["full_name", "home_store_id", "certifications", "hourly_rate_cents"])
    full_name = as_str(data, "full_name")
    home_store_id = as_str(data, "home_store_id")
    if home_store_id not in db.stores:
        raise ApiError("ERR_STORE_NOT_FOUND", 404, "home_store_id not found")
    certifications = data.get("certifications")
    if not isinstance(certifications, list) or not all(isinstance(c, str) for c in certifications):
        raise ApiError("ERR_INVALID_REQUEST", 400, "certifications must be a list of strings")
    hourly_rate = as_int(data, "hourly_rate_cents")
    if hourly_rate < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "hourly_rate_cents must be >= 0")
    now = CLOCK.now()
    tid = gen_uuid()
    t = {
        "id": tid,
        "full_name": full_name,
        "home_store_id": home_store_id,
        "certifications": list(certifications),
        "hourly_rate_cents": hourly_rate,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.trainers[tid] = t
    return success_object(serialize_trainer(t), 201)


@app.route("/trainers", methods=["GET"])
def list_trainers():
    require_role(VALID_ROLES)
    limit, offset = get_pagination()
    home_store_id = request.args.get("home_store_id")
    items = list(db.trainers.values())
    if home_store_id:
        items = [t for t in items if t["home_store_id"] == home_store_id]
    items.sort(key=lambda t: t["created_at"])
    page, total = paginate_list(items, limit, offset)
    return success_array([serialize_trainer(t) for t in page], limit, offset, total)


@app.route("/trainers/<trainer_id>", methods=["GET"])
def get_trainer(trainer_id):
    require_role(VALID_ROLES)
    t = require_trainer(trainer_id)
    return success_object(serialize_trainer(t))


# ============================================================================
# Bookings
# ============================================================================
@app.route("/members/<member_id>/bookings", methods=["POST"])
def create_booking(member_id):
    user_id, role = require_role({"Member", "StoreManager"})
    member = require_member(member_id)
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    data = body()
    require_fields(data, ["booking_kind"])
    booking_kind = as_str(data, "booking_kind")
    if booking_kind not in ("GROUP_CLASS", "PERSONAL_TRAINING"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid booking_kind")
    class_session_id = as_str(data, "class_session_id", required=False, allow_none=True)
    trainer_id = as_str(data, "trainer_id", required=False, allow_none=True)
    starts_at = as_iso(data, "starts_at", required=False, allow_none=True)
    ends_at = as_iso(data, "ends_at", required=False, allow_none=True)
    applied_coupon_id = as_str(data, "applied_coupon_id", required=False, allow_none=True)

    if booking_kind == "GROUP_CLASS":
        if not class_session_id:
            raise ApiError("ERR_INVALID_REQUEST", 400, "class_session_id required for GROUP_CLASS")
        if trainer_id:
            raise ApiError("ERR_INVALID_REQUEST", 400, "trainer_id must be null for GROUP_CLASS")
        cs = db.class_sessions.get(class_session_id)
        if cs is None:
            raise ApiError("ERR_CLASS_SESSION_NOT_FOUND", 404, "ClassSession not found")
        store_id = cs["store_id"]
        # starts/ends must match (or be omitted). PRD §3.6 packages both the
        # lead-time gate and the "must equal ClassSession.starts_at exactly"
        # gate under ERR_BOOKING_LEAD_TIME.
        if starts_at is not None and starts_at != cs["starts_at"]:
            raise ApiError("ERR_BOOKING_LEAD_TIME", 409, "starts_at must equal ClassSession.starts_at")
        if ends_at is not None and ends_at != cs["ends_at"]:
            raise ApiError("ERR_BOOKING_LEAD_TIME", 409, "ends_at must equal ClassSession.ends_at")
        starts_at = cs["starts_at"]
        ends_at = cs["ends_at"]
        trainer = None
    else:
        if not trainer_id:
            raise ApiError("ERR_INVALID_REQUEST", 400, "trainer_id required for PERSONAL_TRAINING")
        if class_session_id:
            raise ApiError("ERR_INVALID_REQUEST", 400, "class_session_id must be null for PERSONAL_TRAINING")
        trainer = require_trainer(trainer_id)
        if starts_at is None or ends_at is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "starts_at and ends_at required for PT")
        if ends_at <= starts_at:
            raise ApiError("ERR_INVALID_REQUEST", 400, "ends_at must be > starts_at")
        store_id = trainer["home_store_id"]
        cs = None

    coupon = None
    if applied_coupon_id is not None:
        coupon = db.coupons.get(applied_coupon_id)
        if coupon is None:
            raise ApiError("ERR_COUPON_NOT_FOUND", 404, "Coupon not found")
        coupon_set_status_if_needed(coupon)

    # ----- Validation ordering per PRD §2.13 -----
    # priority 4: state preconditions on target
    if cs is not None and cs["status"] not in ("SCHEDULED",):
        raise ApiError("ERR_INVALID_STATE", 409, f"ClassSession status={cs['status']} does not allow new bookings")

    # priority 5: account-posture gate
    now = CLOCK.now()
    posture = member["account_posture"]
    # For GROUP_CLASS bookings: posture OPEN -> RESERVED/WAITLISTED;
    #                          posture RESTRICTED -> WAITLISTED join allowed;
    #                          posture FROZEN -> forbidden.
    # For PERSONAL_TRAINING: always requires OPEN (no waitlist concept).
    if posture == "FROZEN":
        raise ApiError("ERR_ACCOUNT_POSTURE_FROZEN", 403, "Member is FROZEN")
    if booking_kind == "PERSONAL_TRAINING" and posture != "OPEN":
        raise ApiError("ERR_ACCOUNT_POSTURE_FROZEN", 403, "PT requires posture OPEN")

    # priority 6: cross-store tier permission
    if store_id != member["home_store_id"] and member["tier"] == "BASIC":
        raise ApiError("ERR_CROSS_STORE_NOT_ALLOWED_FOR_TIER", 403, "BASIC tier cannot book at non-home store")

    # priority 7: minimum-tier
    if cs is not None:
        min_tier = cs.get("minimum_tier", "BASIC")
        if TIER_RANK.get(member["tier"], 0) < TIER_RANK.get(min_tier, 0):
            raise ApiError("ERR_TIER_BELOW_MINIMUM", 403, f"Member.tier={member['tier']} < minimum_tier={min_tier}")

    # priority 8: member time conflict
    for b in db.bookings.values():
        if b["member_id"] != member_id:
            continue
        if b["status"] in ("CANCELLED", "NO_SHOW", "ATTENDED"):
            continue
        if b["status"] == "WAITLISTED":
            # Waitlisted bookings do not occupy a seat, so they typically should not conflict either.
            continue
        bs, be = b["starts_at"], b["ends_at"]
        # half-open overlap [starts_at, ends_at)
        if bs < ends_at and starts_at < be:
            raise ApiError("ERR_MEMBER_TIME_CONFLICT", 409, "Overlaps another booking")

    # priority 9: trainer availability (PT only)
    if booking_kind == "PERSONAL_TRAINING":
        env_start = starts_at - timedelta(minutes=TRAINER_BUFFER_MINUTES)
        env_end = ends_at + timedelta(minutes=TRAINER_BUFFER_MINUTES)
        for b in db.bookings.values():
            if b["booking_kind"] != "PERSONAL_TRAINING":
                continue
            if b.get("trainer_id") != trainer_id:
                continue
            if b["status"] not in ("RESERVED", "CONFIRMED"):
                continue
            bs, be = b["starts_at"], b["ends_at"]
            # closed-on-both-sides envelope overlap (adjacency IS conflict)
            if bs <= env_end and be >= env_start:
                raise ApiError("ERR_TRAINER_UNAVAILABLE", 409, "Trainer busy in 15-min buffer window")

    # priority 11: lead time (GROUP_CLASS)
    if booking_kind == "GROUP_CLASS":
        if (starts_at - now).total_seconds() / 60.0 < MIN_LEAD_MINUTES:
            raise ApiError("ERR_BOOKING_LEAD_TIME", 409, f"Less than {MIN_LEAD_MINUTES} minutes lead time")

    # priority 12: coupon validity
    if coupon is not None:
        coupon_validate_redeemable(coupon, "BOOKING", member=member)

    # Decide initial status (capacity routing for GROUP_CLASS)
    waitlist_position = None
    initial_status = "RESERVED"
    had_seat = True
    if booking_kind == "GROUP_CLASS":
        if cs["reserved_seat_count"] >= cs["capacity"]:
            initial_status = "WAITLISTED"
            had_seat = False
        elif posture == "RESTRICTED":
            # RESTRICTED can only join waitlist
            initial_status = "WAITLISTED"
            had_seat = False
    # If WAITLISTED, compute next waitlist_position
    if initial_status == "WAITLISTED" and cs is not None:
        siblings = [b for b in db.bookings.values()
                    if b.get("class_session_id") == class_session_id and b["status"] == "WAITLISTED"]
        siblings.sort(key=lambda b: b["created_at"])
        waitlist_position = len(siblings) + 1

    booking_id = gen_uuid()
    booking = {
        "id": booking_id,
        "member_id": member_id,
        "booking_kind": booking_kind,
        "class_session_id": class_session_id,
        "trainer_id": trainer_id,
        "store_id": store_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "applied_coupon_id": applied_coupon_id,
        "waitlist_position": waitlist_position,
        "provisional_price_cents": 0,
        "final_price_cents": None,
        "status": initial_status,
        "gate_check_in_at": None,
        "_had_seat": had_seat,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    booking["provisional_price_cents"] = booking_provisional_price(
        booking_kind=booking_kind,
        class_session=cs,
        trainer=trainer,
        member_tier=member["tier"],
        starts_at=starts_at,
        ends_at=ends_at,
        coupon=coupon,
        now=now,
    )
    db.bookings[booking_id] = booking
    if had_seat and cs is not None:
        cs["reserved_seat_count"] += 1
        bump(cs)
    if coupon is not None:
        coupon_increment(coupon)

    return success_object(serialize_booking(booking), 201)


@app.route("/members/<member_id>/bookings", methods=["GET"])
def list_bookings(member_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    require_member(member_id)
    limit, offset = get_pagination()
    status_f = request.args.get("status")
    kind_f = request.args.get("booking_kind")
    items = [b for b in db.bookings.values() if b["member_id"] == member_id]
    if status_f:
        items = [b for b in items if b["status"] == status_f]
    if kind_f:
        items = [b for b in items if b["booking_kind"] == kind_f]
    items.sort(key=lambda b: b["created_at"])
    page, total = paginate_list(items, limit, offset)
    return success_array([serialize_booking(b) for b in page], limit, offset, total)


@app.route("/members/<member_id>/bookings/<booking_id>", methods=["GET"])
def get_booking(member_id, booking_id):
    user_id, role = require_role({"Member", "BillingAdmin", "StoreManager", "Trainer"})
    b = require_booking(member_id, booking_id)
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    elif role == "Trainer":
        # Only allowed for bookings they lead
        leads_pt = (b.get("trainer_id") == user_id)
        cs = db.class_sessions.get(b.get("class_session_id")) if b.get("class_session_id") else None
        leads_class = cs is not None and cs.get("trainer_id") == user_id
        if not (leads_pt or leads_class):
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "Trainer can only view own bookings")
    return success_object(serialize_booking(b))


@app.route("/members/<member_id>/bookings/<booking_id>/confirm", methods=["POST"])
def confirm_booking(member_id, booking_id):
    user_id, role = require_role({"Member"})
    check_member_ownership(member_id, user_id, role)
    member = require_member(member_id)
    b = require_booking(member_id, booking_id)
    data = body()
    check_occ(b, data)
    if b["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, f"Cannot confirm from status={b['status']}")
    if member["account_posture"] != "OPEN":
        raise ApiError("ERR_ACCOUNT_POSTURE_FROZEN", 403, "Member posture not OPEN")
    if b.get("class_session_id"):
        cs = db.class_sessions.get(b["class_session_id"])
        if cs is not None:
            cutoff = cs["starts_at"] - timedelta(minutes=CONFIRM_CUTOFF_MINUTES)
            if CLOCK.now() >= cutoff:
                raise ApiError("ERR_INVALID_STATE", 409, "Past confirmation cutoff")
    b["status"] = "CONFIRMED"
    bump(b)
    return success_object(serialize_booking(b))


@app.route("/members/<member_id>/bookings/<booking_id>/check-in", methods=["POST"])
def check_in_booking(member_id, booking_id):
    # The PRD lists this as 'system' role; we'll accept BillingAdmin as a stand-in
    # since 'system' is not in our VALID_ROLES set. The /_events/emit path is the
    # canonical way to fire this; this direct endpoint exists for completeness.
    require_role({"BillingAdmin"})
    member = require_member(member_id)
    b = require_booking(member_id, booking_id)
    data = body()
    if b["status"] in ("ATTENDED", "NO_SHOW", "CANCELLED"):
        raise ApiError("ERR_BOOKING_TERMINAL", 409, "Booking is in terminal state")
    if b["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, f"Cannot check-in from status={b['status']}")
    if member["account_posture"] != "OPEN":
        raise ApiError("ERR_ACCOUNT_POSTURE_FROZEN", 403, "Member posture not OPEN")
    cs = db.class_sessions.get(b.get("class_session_id"))
    now = CLOCK.now()
    if cs is not None:
        window_start = cs["starts_at"] - timedelta(minutes=CHECK_IN_PREWINDOW_MINUTES)
        window_end = cs["ends_at"]
        if not (window_start <= now <= window_end):
            raise ApiError("ERR_INVALID_STATE", 409, "Outside check-in window")
    b["gate_check_in_at"] = now
    b["status"] = "ATTENDED"
    b["final_price_cents"] = b["provisional_price_cents"]
    bump(b)
    return success_object(serialize_booking(b))


@app.route("/members/<member_id>/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(member_id, booking_id):
    user_id, role = require_role({"Member", "StoreManager"})
    member = require_member(member_id)
    b = require_booking(member_id, booking_id)
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    data = body()
    check_occ(b, data)
    if b["status"] in ("ATTENDED", "NO_SHOW", "CANCELLED"):
        raise ApiError("ERR_BOOKING_TERMINAL", 409, "Booking already terminal")
    if role == "StoreManager":
        services._cancel_booking_admin(b, member, reason="store_manager_cancel")
    else:
        cancel_booking_member(b, member)
    return success_object(serialize_booking(b))


# ============================================================================
# Coupons
# ============================================================================
@app.route("/coupons", methods=["POST"])
def create_coupon():
    require_role({"BillingAdmin"})
    data = body()
    require_fields(data, ["code", "kind", "value", "applicable_to", "valid_from", "valid_until", "max_redemptions"])
    code = as_str(data, "code")
    kind = as_str(data, "kind")
    value = as_int(data, "value")
    applicable_to = as_str(data, "applicable_to")
    valid_from = as_iso(data, "valid_from")
    valid_until = as_iso(data, "valid_until")
    max_redemptions = as_int(data, "max_redemptions")
    if not COUPON_CODE_RE.match(code):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid coupon code format")
    if kind not in ("PERCENT_OFF", "FIXED_OFF_CENTS", "REFERRAL_REWARD"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid kind")
    if applicable_to not in ("SUBSCRIPTION", "BOOKING", "BOTH"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid applicable_to")
    if kind == "PERCENT_OFF" and not (0 <= value <= 100):
        raise ApiError("ERR_INVALID_REQUEST", 400, "PERCENT_OFF value must be 0..100")
    if value < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "value must be >= 0")
    if max_redemptions < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "max_redemptions must be >= 1")
    if valid_until <= valid_from:
        raise ApiError("ERR_INVALID_REQUEST", 400, "valid_until must be > valid_from")
    if any(c["code"] == code for c in db.coupons.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Coupon code already exists")
    now = CLOCK.now()
    cid = gen_uuid()
    coupon = {
        "id": cid,
        "code": code,
        "kind": kind,
        "value": value,
        "applicable_to": applicable_to,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "max_redemptions": max_redemptions,
        "redemption_count": 0,
        "status": "ACTIVE",
        "tied_to_member_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    coupon_set_status_if_needed(coupon)
    db.coupons[cid] = coupon
    return success_object(serialize_coupon(coupon), 201)


@app.route("/coupons", methods=["GET"])
def list_coupons():
    require_role({"BillingAdmin", "StoreManager"})
    limit, offset = get_pagination()
    status_f = request.args.get("status")
    items = list(db.coupons.values())
    for c in items:
        coupon_set_status_if_needed(c)
    if status_f:
        items = [c for c in items if c["status"] == status_f]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate_list(items, limit, offset)
    return success_array([serialize_coupon(c) for c in page], limit, offset, total)


@app.route("/coupons/<coupon_id>", methods=["GET"])
def get_coupon(coupon_id):
    require_role({"BillingAdmin", "StoreManager", "Member"})
    c = require_coupon(coupon_id)
    return success_object(serialize_coupon(c))


@app.route("/coupons/<coupon_id>/verify", methods=["POST"])
def verify_coupon(coupon_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    c = require_coupon(coupon_id)
    data = body()
    require_fields(data, ["context_kind"])
    context_kind = as_str(data, "context_kind")
    if context_kind not in ("BOOKING", "SUBSCRIPTION", "BOTH"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid context_kind")
    member = None
    if role == "Member":
        member = db.members.get(user_id)
    coupon_validate_redeemable(c, context_kind if context_kind != "BOTH" else "BOOKING", member=member)
    return success_object(serialize_coupon(c))


# ============================================================================
# Referrals & Wallet
# ============================================================================
@app.route("/members/<member_id>/referrals", methods=["GET"])
def list_referrals(member_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    require_member(member_id)
    limit, offset = get_pagination()
    items = [r for r in db.referrals.values() if r["sponsor_member_id"] == member_id]
    items.sort(key=lambda r: r["created_at"])
    page, total = paginate_list(items, limit, offset)
    return success_array([serialize_referral(r) for r in page], limit, offset, total)


@app.route("/members/<member_id>/wallet", methods=["GET"])
def get_wallet(member_id):
    user_id, role = require_role({"Member", "BillingAdmin"})
    if role == "Member":
        check_member_ownership(member_id, user_id, role)
    member = require_member(member_id)
    return success_object(serialize_wallet(member))


# ============================================================================
# Test-driving capabilities
# ============================================================================
@app.route("/_test/reset", methods=["POST"])
def test_reset():
    """Reset all in-memory state and the logical clock. Test-driving capability,
    invoked by the test harness between tests to ensure deterministic isolation.

    Not in PRD §4's endpoint table — it exists alongside the other documented
    test-driving capabilities (clock-advance, sweep-run, event-emit) as part of
    the test-harness contract.
    """
    db.reset_all()
    CLOCK.reset()
    seed_stores()
    return success_object({"now": iso_now()})


@app.route("/_clock/advance", methods=["POST"])
def clock_advance():
    require_role({"BillingAdmin"})
    data = body()
    require_fields(data, ["to_timestamp"])
    target = as_iso(data, "to_timestamp")
    CLOCK.advance_to(target)
    clock_advance_cascades()
    return success_object({"now": iso_now()})


@app.route("/_sweep/run", methods=["POST"])
def run_sweep():
    require_role({"BillingAdmin"})
    sweep_run()
    return success_object({"now": iso_now()})


@app.route("/_events/emit", methods=["POST"])
def emit_event():
    require_role({"BillingAdmin"})
    data = body()
    require_fields(data, ["event_kind", "event_payload"])
    kind = as_str(data, "event_kind")
    payload = data.get("event_payload") or {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "event_payload must be an object")
    if kind == "gate_check_in":
        # synthesize a check-in
        member_id = payload.get("member_id")
        booking_id = payload.get("booking_id")
        if not member_id or not booking_id:
            raise ApiError("ERR_INVALID_REQUEST", 400, "member_id and booking_id required")
        member = require_member(member_id)
        b = require_booking(member_id, booking_id)
        if b["status"] in ("ATTENDED", "NO_SHOW", "CANCELLED"):
            raise ApiError("ERR_BOOKING_TERMINAL", 409, "Booking is terminal")
        if b["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE", 409, f"Cannot check-in from status={b['status']}")
        if member["account_posture"] != "OPEN":
            raise ApiError("ERR_ACCOUNT_POSTURE_FROZEN", 403, "Member posture not OPEN")
        cs = db.class_sessions.get(b.get("class_session_id"))
        now = CLOCK.now()
        if cs is not None:
            window_start = cs["starts_at"] - timedelta(minutes=CHECK_IN_PREWINDOW_MINUTES)
            window_end = cs["ends_at"]
            if not (window_start <= now <= window_end):
                raise ApiError("ERR_INVALID_STATE", 409, "Outside check-in window")
        b["gate_check_in_at"] = now
        b["status"] = "ATTENDED"
        b["final_price_cents"] = b["provisional_price_cents"]
        bump(b)
        return success_object(serialize_booking(b))
    elif kind == "payment_gateway":
        # synthesize a payment-attempt result for a subscription
        member_id = payload.get("member_id")
        sub_id = payload.get("subscription_id")
        outcome = payload.get("outcome")
        gateway_txn_id = payload.get("gateway_txn_id")
        idempotency_key = payload.get("idempotency_key")
        failure_reason = payload.get("failure_reason")
        if not all([member_id, sub_id, outcome, gateway_txn_id, idempotency_key]):
            raise ApiError("ERR_INVALID_REQUEST", 400, "missing payment_gateway payload fields")
        member = require_member(member_id)
        sub = require_subscription(member_id, sub_id)
        for pa in db.payment_attempts.values():
            if pa["subscription_id"] == sub_id and pa["idempotency_key"] == idempotency_key:
                return error_response("ERR_IDEMPOTENT_REPLAY", 200, "Replay")
        # Compute attempt_number & expected amount
        period_start = sub.get("current_period_start")
        period_attempts = [pa for pa in db.payment_attempts.values()
                           if pa["subscription_id"] == sub_id and
                           (period_start is None or pa["created_at"] >= period_start)]
        attempt_number = len(period_attempts) + 1
        coupon = db.coupons.get(sub.get("applied_coupon_id")) if sub.get("applied_coupon_id") else None
        expected_amount, _, _ = subscription_charge_amount(sub, member, coupon)
        if attempt_number > 1:
            first = next((pa for pa in period_attempts if pa["attempt_number"] == 1), None)
            if first is not None:
                expected_amount = first["amount_cents"]
        attempt_id = gen_uuid()
        pa = process_payment_attempt(
            member=member, subscription=sub, outcome=outcome,
            attempt_id=attempt_id, attempt_number=attempt_number,
            amount_cents=expected_amount, gateway_txn_id=gateway_txn_id,
            idempotency_key=idempotency_key, failure_reason=failure_reason,
        )
        return success_object(serialize_payment_attempt(pa), 201)
    else:
        return success_object({"ack": True, "event_kind": kind})


# ============================================================================
# Bootstrap
# ============================================================================
def seed_stores():
    """Seed Stores at boot per PRD §3.9.

    PRD §4 lists no POST /stores endpoint, so the directory is read-only to the
    public surface. The implementation must seed the directory with at least one
    Store per state_code so registration (which requires a home_store_id) can
    succeed. Seed CA, NY, TX — the three state_codes whose refund and penalty
    rules PRD §3 enumerates by name.
    """
    now = CLOCK.now()
    seed_specs = [
        ("CA", "Bay Area Fitness", "06:00", "22:00", "GATE-CA-01"),
        ("NY", "Manhattan Strength", "06:00", "22:00", "GATE-NY-01"),
        ("TX", "Austin Lifting Club", "06:00", "22:00", "GATE-TX-01"),
    ]
    for state_code, name, opens, closes, gate in seed_specs:
        sid = gen_uuid()
        db.stores[sid] = {
            "id": sid,
            "name": name,
            "state_code": state_code,
            "opens_at_local": opens,
            "closes_at_local": closes,
            "gate_device_id": gate,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }


seed_stores()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
