"""Reporting and test-driving endpoints (PRD §3.8, §3.7, §3.9)."""
from flask import Blueprint

import errors
import serializers as S
import validate as V
from db import db, touch
from middleware import authenticate, require_role
from response import success
from util import parse_dt
from services import ticks

bp = Blueprint("admin", __name__)


# =============================================================================
# MRR / churn reporting (PRD §3.8)
# =============================================================================
@bp.route("/reporting/mrr", methods=["GET"])
def reporting_mrr():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    from flask import request

    since_raw = request.args.get("since")
    since = parse_dt(since_raw) if since_raw is not None else None

    total_mrr = 0
    active_sub_count = 0
    # total_mrr_cents = committed MRR across all ACTIVE accounts (PRD §3.8).
    for sub in db.subscriptions.values():
        if sub["lifecycle_status"] != "ACTIVE":
            continue
        account = db.accounts.get(sub["account_id"])
        if account is None or account["status"] != "ACTIVE":
            continue
        total_mrr += sub["mrr_contribution_cents"]
        active_sub_count += 1

    churned_count = 0
    churned_mrr = 0
    for sub in db.subscriptions.values():
        churned_at = sub.get("_churned_at")
        if churned_at is None:
            continue
        if since is not None and churned_at < since:
            continue
        churned_count += 1
        churned_mrr += sub.get("_churned_mrr_cents", 0)

    return success({
        "total_mrr_cents": total_mrr,
        "active_subscription_count": active_sub_count,
        "churned_subscription_count": churned_count,
        "churned_mrr_cents": churned_mrr,
    })


# =============================================================================
# Test-driving: clock (PRD §3.9)
# =============================================================================
@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    body = V.get_body()
    to_iso = V.require_str(body, "to_iso8601")
    dt = parse_dt(to_iso)
    db.set_clock(dt)
    from util import iso
    return success({"now": iso(dt)})


# =============================================================================
# Test-driving: payment card state (PRD §3.7)
# =============================================================================
@bp.route("/_payments/set-card-state", methods=["POST"])
def set_card_state():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    body = V.get_body()
    account_id = V.require_str(body, "account_id")
    payment_method_ok = V.require_bool(body, "payment_method_ok")
    account = db.accounts.get(account_id)
    if account is None:
        raise errors.not_found("Account not found")
    account["payment_method_ok"] = payment_method_ok
    touch(account)
    return success(S.ser_account(account))


# =============================================================================
# Test-driving: billing ticks (PRD §3.3, §3.7)
# =============================================================================
@bp.route("/_billing/run-renewals", methods=["POST"])
def run_renewals():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    result = ticks.run_renewals()
    return success(result)


@bp.route("/_billing/run-dunning", methods=["POST"])
def run_dunning():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    result = ticks.run_dunning()
    return success(result)
