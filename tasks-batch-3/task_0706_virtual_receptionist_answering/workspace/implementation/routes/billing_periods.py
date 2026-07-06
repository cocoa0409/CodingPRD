"""BillingPeriod routes (PRD §3.8, §3.9, §3.11)."""
from flask import Blueprint, request

import errors
import serializers
from db import db
from response import success_object, success_array
from middleware import get_auth, require_role, ROLE_ADMIN, ROLE_OWNER
from common import (get_body, make_record, paginate, public, touch, as_int)
from services.lookups import find_or_404, require_account_owner
from services import billing

bp = Blueprint("billing_periods", __name__)


def _serialize_with_provisional(period):
    """Serialize a period; an OPEN period reports the provisional overage variant
    (PRD §3.8). A non-OPEN period reports its persisted (final) figures."""
    out = serializers.billing_period(public(period))
    if period["status"] == "OPEN":
        breakdown = billing.provisional_breakdown(period)
        out["consumed_units"] = breakdown["consumed_units"]
        out["overage_units"] = breakdown["overage_units"]
        out["overage_charge_cents"] = breakdown["overage_charge_cents"]
    return out


@bp.route("/va/billing-periods/<period_id>", methods=["GET"])
def get_period(period_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    rec = find_or_404(db.billing_periods, period_id)
    require_account_owner(rec["account_id"], user_id, role)
    return success_object(_serialize_with_provisional(rec), 200)


@bp.route("/va/billing-periods", methods=["GET"])
def list_periods():
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    records = list(db.billing_periods.values())
    account_id = request.args.get("account_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if plan_id is not None:
        records = [r for r in records if r["plan_id"] == plan_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if role == ROLE_OWNER:
        records = [r for r in records if r["account_id"] == user_id]
    page, meta = paginate(records)
    return success_array([_serialize_with_provisional(r) for r in page], meta, 200)


@bp.route("/va/billing-periods/<period_id>/overage-summary", methods=["GET"])
def overage_summary(period_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    rec = find_or_404(db.billing_periods, period_id)
    require_account_owner(rec["account_id"], user_id, role)
    breakdown = billing.provisional_breakdown(rec)
    return success_object(breakdown, 200)


@bp.route("/va/billing-periods/<period_id>/close", methods=["POST"])
def close_period(period_id):
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN})
    rec = find_or_404(db.billing_periods, period_id)
    body = get_body()

    # OCC (priority 5) before state (priority 6).
    expected_period_version = as_int(body, "expected_period_version", required=True)
    if expected_period_version != rec["version"]:
        raise errors.err(errors.ERR_STALE_PERIOD_VERSION, "expected_period_version is stale")

    if rec["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Period is not OPEN")

    # No own call may be DISPUTED (priority 14).
    for c in db.calls.values():
        if c["_period_id"] == rec["id"] and c["billing_status"] == "DISPUTED":
            raise errors.err(errors.ERR_OPEN_DISPUTE, "Period has a DISPUTED call")

    # Finalize overage under the final variant.
    billing.recompute_period_final(rec)
    rec["status"] = "PENDING_CLOSE"
    touch(rec)
    return success_object(serializers.billing_period(public(rec)), 200)


@bp.route("/va/billing-periods/<period_id>/finalize", methods=["POST"])
def finalize_period(period_id):
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN})
    rec = find_or_404(db.billing_periods, period_id)

    if rec["status"] != "PENDING_CLOSE":
        raise errors.err(errors.ERR_INVALID_STATE, "Period is not PENDING_CLOSE")

    rec["status"] = "CLOSED"
    touch(rec)

    account = db.accounts[rec["account_id"]]
    # Open a fresh OPEN period with period_index + 1 (PRD §3.11).
    new_period = make_record({
        "account_id": rec["account_id"],
        "plan_id": account["plan_id"],
        "period_index": rec["period_index"] + 1,
        "included_units": _included_units_for(account),
        "consumed_units": 0,
        "overage_units": 0,
        "overage_charge_cents": 0,
        "status": "OPEN",
    })
    db.billing_periods[new_period["id"]] = new_period
    account["current_period_id"] = new_period["id"]
    touch(account)

    # If the period that just closed had overage_units == 0, set account ACTIVE.
    if rec["overage_units"] == 0:
        if account["status"] != "ACTIVE":
            account["status"] = "ACTIVE"
            touch(account)

    return success_object(serializers.billing_period(public(rec)), 200)


def _included_units_for(account):
    plan = db.service_plans[account["plan_id"]]
    return plan["included_minutes"] if plan["billing_model"] == "PER_MINUTE" else plan["included_calls"]
