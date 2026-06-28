"""Subscription routes (PRD §3.7)."""
from flask import Blueprint, request

from clock import clock, parse_iso8601
from db import db, create_versioned, touch
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SUBSCRIPTION_EXISTS,
    ERR_GRACE_NOT_ELAPSED, ERR_STALE_VERSION, ERR_UPGRADE_NOT_ALLOWED,
)
from helpers import (
    get_json_body, require_fields, require_enum, parse_pagination, paginate,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_subscription
from services.common import get_or_404, require_account_owner, assert_not_purge_pending
from services.calculations import compute_upgrade_charge, PREMIUM_ANNUAL_FEE_CENTS

subscriptions_bp = Blueprint("subscriptions", __name__)

DEFAULT_TERM_DAYS = 365


def _started_on_iso():
    from clock import format_iso8601
    return format_iso8601(clock.now())


@subscriptions_bp.route("/dna/subscriptions", methods=["POST"])
def create_subscription():
    user_id, role = require_roles({"Account"})
    body = get_json_body()
    require_fields(body, ["account_id", "tier", "annual_fee_cents"])

    account = get_or_404(db.accounts, body["account_id"])
    require_account_owner(account["id"], user_id, role)

    # purge-in-progress freeze (priority 8): creating a subscription is blocked.
    assert_not_purge_pending(account["id"])

    require_enum(body["tier"], {"BASIC", "PREMIUM"}, "tier")
    fee = body["annual_fee_cents"]
    if not isinstance(fee, int) or isinstance(fee, bool) or fee < 0:
        raise err(ERR_INVALID_REQUEST, "annual_fee_cents must be an integer >= 0")

    # Single-subscription rule (priority 11): only one ACTIVE/GRACE per account.
    for s in db.subscriptions.values():
        if s["account_id"] == account["id"] and s["status"] in ("ACTIVE", "GRACE"):
            raise err(ERR_SUBSCRIPTION_EXISTS,
                      "Account already has an ACTIVE or GRACE subscription")

    rec = create_versioned(db.subscriptions, {
        "account_id": account["id"],
        "tier": body["tier"],
        "status": "ACTIVE",
        "started_on": _started_on_iso(),
        "term_days": DEFAULT_TERM_DAYS,
        "annual_fee_cents": fee,
        "last_charge_cents": fee,
    })
    return success(serialize_subscription(rec), status=201)


@subscriptions_bp.route("/dna/subscriptions/<rid>", methods=["GET"])
def get_subscription(rid):
    user_id, role = require_roles({"PlatformAdmin", "Account"})
    rec = get_or_404(db.subscriptions, rid)
    require_account_owner(rec["account_id"], user_id, role)
    return success(serialize_subscription(rec), status=200)


@subscriptions_bp.route("/dna/subscriptions", methods=["GET"])
def list_subscriptions():
    user_id, role = require_roles({"PlatformAdmin", "Account"})
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")

    items = list(db.subscriptions.values())
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    if role == "Account":
        items = [s for s in items if s["account_id"] == user_id]

    window, total = paginate(items, limit, offset)
    return list_success(
        [serialize_subscription(s) for s in window], limit, offset, total
    )


def _elapsed_days(started_on_iso):
    """Whole days from started_on date to current logical-clock date, floor."""
    started = parse_iso8601(started_on_iso)
    now = clock.now()
    delta = now - started
    days = delta.days
    if days < 0:
        days = 0
    return days


@subscriptions_bp.route("/dna/subscriptions/<rid>/upgrade", methods=["POST"])
def upgrade_subscription(rid):
    user_id, role = require_roles({"Account"})
    rec = get_or_404(db.subscriptions, rid)
    require_account_owner(rec["account_id"], user_id, role)

    body = get_json_body()
    # expected_subscription_version mandatory (§2.9).
    require_fields(body, ["expected_subscription_version"])

    # State precondition (priority 5): subscription ACTIVE.
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Subscription is not ACTIVE")

    # Upgrade allowed only when tier == BASIC and requested tier == PREMIUM.
    # Requested tier defaults to PREMIUM; if a tier is given it must be PREMIUM.
    requested_tier = body.get("tier", "PREMIUM")
    if rec["tier"] != "BASIC" or requested_tier != "PREMIUM":
        raise err(ERR_UPGRADE_NOT_ALLOWED,
                  "Upgrade requires a BASIC subscription upgrading to PREMIUM")

    # OCC (priority 16): expected must equal live version.
    if body["expected_subscription_version"] != rec["version"]:
        raise err(ERR_STALE_VERSION, "expected_subscription_version does not match")

    # Prorated successor charge.
    elapsed = _elapsed_days(rec["started_on"])
    charge = compute_upgrade_charge(rec, elapsed)

    successor = create_versioned(db.subscriptions, {
        "account_id": rec["account_id"],
        "tier": "PREMIUM",
        "status": "ACTIVE",
        "started_on": _started_on_iso(),
        "term_days": DEFAULT_TERM_DAYS,
        "annual_fee_cents": PREMIUM_ANNUAL_FEE_CENTS,
        "last_charge_cents": charge,
    })

    # Original moves ACTIVE -> SUPERSEDED; version bumped.
    rec["status"] = "SUPERSEDED"
    touch(rec)

    # account.active_subscription_id is derived; reconciled automatically since
    # the superseded sub is no longer ACTIVE/GRACE and the successor is ACTIVE.
    return success(serialize_subscription(successor), status=200)


@subscriptions_bp.route("/dna/subscriptions/<rid>/cancel", methods=["POST"])
def cancel_subscription(rid):
    user_id, role = require_roles({"Account"})
    rec = get_or_404(db.subscriptions, rid)
    require_account_owner(rec["account_id"], user_id, role)

    # ACTIVE -> GRACE.
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Only an ACTIVE subscription may be cancelled")

    rec["status"] = "GRACE"
    touch(rec)
    return success(serialize_subscription(rec), status=200)


@subscriptions_bp.route("/dna/subscriptions/<rid>/expire", methods=["POST"])
def expire_subscription(rid):
    require_roles({"PlatformAdmin"})
    rec = get_or_404(db.subscriptions, rid)

    # GRACE -> CANCELLED.
    if rec["status"] != "GRACE":
        raise err(ERR_INVALID_STATE, "Only a GRACE subscription may be expired")

    # Temporal: clock >= started_on + term_days (priority 12).
    started = parse_iso8601(rec["started_on"])
    from datetime import timedelta
    term_end = started + timedelta(days=rec["term_days"])
    if clock.now() < term_end:
        raise err(ERR_GRACE_NOT_ELAPSED, "Subscription term has not yet elapsed")

    rec["status"] = "CANCELLED"
    touch(rec)
    # account.active_subscription_id derived -> becomes null (no ACTIVE/GRACE).
    return success(serialize_subscription(rec), status=200)
