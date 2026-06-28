"""Subscription & billing routes: create, charge-cycle, pause, resume, cancel, finalize-cancel."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, common_create_fields, light_create_fields, touch
from clock import clock, parse_iso, iso_millis, iso_instant
from errors import (
    err, ERR_INVALID_STATE, ERR_REFERENCED_NOT_FOUND, ERR_DUPLICATE_SUBSCRIPTION,
    ERR_CYCLE_NOT_DUE, ERR_STALE_VERSION, ERR_VALIDATION, ERR_CANCEL_NOT_DUE,
)
from middleware import get_auth, require_role
from lookup import get_or_404, check_client_owner, paginate
from validate import require_body, require_string, optional_int, require_int, require_datetime
from services.calc import cycle_amounts, pause_refund
from services.domain import resume_subscription, finalize_subscription_cancel
import serialize
from response import success, list_success

bp = Blueprint("subscriptions", __name__)

WEEK = timedelta(days=7)
PAUSE_HORIZON = timedelta(days=84)


@bp.route("/subscriptions", methods=["POST"])
def create_subscription():
    user_id, role = get_auth()
    require_role(role, {"Client", "BillingAdmin"})
    data = require_body(request.get_json(silent=True))
    client_id = require_string(data, "client_id")
    # ownership: a Client may only create for itself
    check_client_owner(role, user_id, client_id)
    client = db.clients.get(client_id)
    if client is None:
        raise err(ERR_REFERENCED_NOT_FOUND, "client_id not found")
    base_fee = optional_int(data, "base_weekly_fee_cents", default=9900, minimum=0)
    weekly_grant = optional_int(data, "weekly_credit_grant", default=1, minimum=0, maximum=4)
    # one non-terminal subscription per client
    for s in db.subscriptions.values():
        if s["client_id"] == client_id and s["status"] != "CANCELLED":
            raise err(ERR_DUPLICATE_SUBSCRIPTION, "Client already has a non-terminal subscription")
    sub = {
        **common_create_fields(),
        "client_id": client_id,
        "status": "TRIALING",
        "base_weekly_fee_cents": base_fee,
        "weekly_credit_grant": weekly_grant,
        "current_period_start": None,
        "pause_resumes_on": None,
        "cancel_effective_on": None,
    }
    db.subscriptions[sub["id"]] = sub
    return success(serialize.subscription_out(sub), status=201)


@bp.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    user_id, role = get_auth()
    require_role(role, {"Client", "BillingAdmin"})
    sub = get_or_404(db.subscriptions, sid)
    check_client_owner(role, user_id, sub["client_id"])
    return success(serialize.subscription_out(sub))


@bp.route("/subscriptions/<sid>/charge-cycle", methods=["POST"])
def charge_cycle(sid):
    user_id, role = get_auth()
    require_role(role, {"BillingAdmin"})
    sub = get_or_404(db.subscriptions, sid)
    if sub["status"] not in ("TRIALING", "ACTIVE"):
        raise err(ERR_INVALID_STATE, "Subscription not chargeable from current state")
    is_renewal = sub["status"] == "ACTIVE"
    now = clock.now()
    if is_renewal:
        cps = parse_iso(sub["current_period_start"])
        if now < cps + WEEK:
            raise err(ERR_CYCLE_NOT_DUE, "Renewal cycle not yet due")
        period_start_dt = cps + WEEK
    else:
        period_start_dt = now
    period_end_dt = period_start_dt + WEEK
    client = db.clients.get(sub["client_id"])
    list_amount, wallet_applied, charged = cycle_amounts(
        sub["base_weekly_fee_cents"], client["financial_aid_tier"], client["wallet_credit_cents"],
    )
    cycle = {
        **common_create_fields(),
        "subscription_id": sid,
        "period_start": iso_instant(period_start_dt),
        "period_end": iso_instant(period_end_dt),
        "list_amount_cents": list_amount,
        "wallet_applied_cents": wallet_applied,
        "charged_amount_cents": charged,
        "status": "PAID",
        "credits_granted": sub["weekly_credit_grant"],
    }
    db.billing_cycles[cycle["id"]] = cycle
    # grant credits
    credit_expiry = iso_instant(period_end_dt + timedelta(days=28))
    for _ in range(sub["weekly_credit_grant"]):
        credit = {
            **light_create_fields(),
            "client_id": sub["client_id"],
            "billing_cycle_id": cycle["id"],
            "status": "AVAILABLE",
            "expires_on": credit_expiry,
            "live_session_id": None,
        }
        db.session_credits[credit["id"]] = credit
    # debit wallet
    client["wallet_credit_cents"] -= wallet_applied
    touch(client)
    # advance subscription
    if is_renewal:
        sub["current_period_start"] = iso_instant(period_start_dt)
    else:
        sub["current_period_start"] = iso_instant(period_start_dt)
        sub["status"] = "ACTIVE"
    touch(sub)
    return success(serialize.billing_cycle_out(cycle), status=201)


@bp.route("/subscriptions/<sid>/billing-cycles", methods=["GET"])
def list_billing_cycles(sid):
    user_id, role = get_auth()
    require_role(role, {"Client", "BillingAdmin"})
    sub = get_or_404(db.subscriptions, sid)
    check_client_owner(role, user_id, sub["client_id"])
    status = request.args.get("status")
    items = [b for b in db.billing_cycles.values()
             if b["subscription_id"] == sid and (status is None or b["status"] == status)]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.billing_cycle_out(b) for b in page], lim, off, total)


@bp.route("/subscriptions/<sid>/pause", methods=["POST"])
def pause_subscription(sid):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    sub = get_or_404(db.subscriptions, sid)
    check_client_owner(role, user_id, sub["client_id"])
    data = require_body(request.get_json(silent=True))
    resume_on = require_datetime(data, "resume_on")
    expected_version = require_int(data, "expected_subscription_version")
    # state
    if sub["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Subscription not in ACTIVE")
    now = clock.now()
    cps = parse_iso(sub["current_period_start"])
    # ERR_VALIDATION: resume_on must be strictly after clock and <= cps + 84 days
    if not (resume_on > now) or resume_on > cps + PAUSE_HORIZON:
        raise err(ERR_VALIDATION, "resume_on outside permitted horizon")
    # OCC
    if expected_version != sub["version"]:
        raise err(ERR_STALE_VERSION, "expected_subscription_version is stale")
    # compute refund from latest PAID billing cycle
    paid_cycles = [b for b in db.billing_cycles.values()
                   if b["subscription_id"] == sid and b["status"] == "PAID"]
    paid_cycles.sort(key=lambda b: (b["created_at"], b["_seq"]))
    paid_cents = paid_cycles[-1]["charged_amount_cents"] if paid_cycles else 0
    elapsed_days = (now - cps).days
    if elapsed_days < 0:
        elapsed_days = 0
    refund = pause_refund(paid_cents, elapsed_days)
    client = db.clients.get(sub["client_id"])
    if refund > 0:
        client["wallet_credit_cents"] += refund
        touch(client)
    # expire current period's AVAILABLE credits (credits granted by cycles of this subscription)
    sub_cycle_ids = {b["id"] for b in db.billing_cycles.values() if b["subscription_id"] == sid}
    for c in db.session_credits.values():
        if c["billing_cycle_id"] in sub_cycle_ids and c["status"] == "AVAILABLE":
            c["status"] = "EXPIRED"
    sub["status"] = "PAUSED"
    sub["pause_resumes_on"] = data["resume_on"]
    touch(sub)
    return success(serialize.subscription_out(sub))


@bp.route("/subscriptions/<sid>/resume", methods=["POST"])
def resume_sub(sid):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    sub = get_or_404(db.subscriptions, sid)
    check_client_owner(role, user_id, sub["client_id"])
    if sub["status"] != "PAUSED":
        raise err(ERR_INVALID_STATE, "Subscription not in PAUSED")
    resume_subscription(sub)
    return success(serialize.subscription_out(sub))


@bp.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_sub(sid):
    user_id, role = get_auth()
    require_role(role, {"Client"})
    sub = get_or_404(db.subscriptions, sid)
    check_client_owner(role, user_id, sub["client_id"])
    if sub["status"] not in ("ACTIVE", "TRIALING"):
        raise err(ERR_INVALID_STATE, "Subscription not in ACTIVE or TRIALING")
    now = clock.now()
    if sub["status"] == "TRIALING":
        effective = now
    else:
        effective = parse_iso(sub["current_period_start"]) + WEEK
    sub["status"] = "CANCEL_SCHEDULED"
    sub["cancel_effective_on"] = iso_instant(effective)
    touch(sub)
    return success(serialize.subscription_out(sub))


@bp.route("/subscriptions/<sid>/finalize-cancel", methods=["POST"])
def finalize_cancel(sid):
    user_id, role = get_auth()
    require_role(role, {"BillingAdmin"})
    sub = get_or_404(db.subscriptions, sid)
    if sub["status"] != "CANCEL_SCHEDULED":
        raise err(ERR_INVALID_STATE, "Subscription not in CANCEL_SCHEDULED")
    now = clock.now()
    if now < parse_iso(sub["cancel_effective_on"]):
        raise err(ERR_CANCEL_NOT_DUE, "Cancellation not yet due")
    finalize_subscription_cancel(sub)
    return success(serialize.subscription_out(sub))
