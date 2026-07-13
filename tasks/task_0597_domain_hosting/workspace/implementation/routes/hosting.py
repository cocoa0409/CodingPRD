"""Hosting plans, subscriptions, metering and overage (PRD 3.6)."""

from flask import Blueprint, request

import config
import db
import middleware as mw
import response
import validation as v
from errors import ApiError
from services import money, overage
from services.serializers import (
    billing_period_out,
    plan_out,
    subscription_out,
    usage_record_out,
)

bp = Blueprint("hosting", __name__)

METERABLE = ("ACTIVE", "OVER_QUOTA")


@bp.post("/hosting-plans")
@mw.roles_required("BillingAdmin")
def create_plan():
    data = v.body()
    plan = db.base_record(with_audit=False)
    plan.update(
        {
            "plan_code": v.req_str(data, "plan_code"),
            "tier": v.req_enum(data, "tier", config.PLAN_TIERS),
            "storage_quota_mb": v.req_int(data, "storage_quota_mb", minimum=0),
            "bandwidth_quota_mb": v.req_int(data, "bandwidth_quota_mb", minimum=0),
            "monthly_price_cents": v.req_int(data, "monthly_price_cents", minimum=0),
            "included_mailboxes": v.req_int(data, "included_mailboxes", minimum=0),
            "included_ssl": v.req_bool(data, "included_ssl"),
            "overage_rate_cents_per_gb": v.req_int(
                data, "overage_rate_cents_per_gb", minimum=0
            ),
        }
    )
    db.hosting_plans[plan["id"]] = plan
    return response.created(plan_out(plan))


@bp.post("/hosting-subscriptions")
@mw.roles_required("Registrant")
def create_subscription():
    data = v.body()
    account_id = v.req_str(data, "account_id")
    plan_id = v.req_str(data, "plan_id")
    primary_domain_id = v.opt_str(data, "primary_domain_id", None, allow_empty=False)

    account = v.get_account(account_id)
    plan = v.get_plan(plan_id)
    domain = v.get_domain(primary_domain_id) if primary_domain_id else None

    mw.require_owner(account["id"])
    if domain is not None:
        mw.require_owner(domain["account_id"])
    mw.gate_account_suspended()

    subscription = db.base_record()
    subscription.update(
        {
            "account_id": account_id,
            "plan_id": plan_id,
            "primary_domain_id": domain["id"] if domain else None,
            "status": "PROVISIONING",
            "storage_committed_mb": 0,
            "bandwidth_used_mb": 0,
            "auto_renew": v.opt_bool(data, "auto_renew", True),
        }
    )
    db.subscriptions[subscription["id"]] = subscription

    money.create_invoice(
        account_id,
        [
            {
                "item_type": "HOSTING_PLAN",
                "reference_id": subscription["id"],
                "description": "Hosting plan %s" % plan["plan_code"],
                "quantity": 1,
                "unit_price_cents": plan["monthly_price_cents"],
            }
        ],
    )
    return response.created(subscription_out(subscription))


@bp.get("/hosting-subscriptions/<subscription_id>")
@mw.roles_required("Registrant", "SupportAgent", "BillingAdmin", "PlatformAdmin")
def read_subscription(subscription_id):
    subscription = v.get_subscription(subscription_id)
    mw.require_owner(subscription["account_id"])
    return response.ok(subscription_out(subscription))


@bp.get("/hosting-subscriptions")
@mw.roles_required("Registrant", "SupportAgent", "BillingAdmin", "PlatformAdmin")
def list_subscriptions():
    limit, offset = v.pagination()
    account_id = request.args.get("account_id")
    plan_id = request.args.get("plan_id")
    primary_domain_id = request.args.get("primary_domain_id")
    status = v.query_enum("status", config.SUBSCRIPTION_STATUSES)

    rows = db.ordered(
        db.subscriptions,
        lambda s: (account_id is None or s["account_id"] == account_id)
        and (plan_id is None or s["plan_id"] == plan_id)
        and (primary_domain_id is None or s["primary_domain_id"] == primary_domain_id)
        and (status is None or s["status"] == status),
    )
    rows = mw.scope_to_registrant(rows, lambda s: s["account_id"])
    page, total = v.paginate(rows, limit, offset, subscription_out)
    return response.listing(page, limit, offset, total)


# ---------------------------------------------------------------- usage
def _open_period_for(subscription, instant):
    for period in db.ordered(
        db.billing_periods,
        lambda p: p["subscription_id"] == subscription["id"] and p["status"] == "OPEN",
    ):
        if period["_period_start"] <= instant < period["_period_end"]:
            return period
    return None


def _refresh_period(period, subscription, plan):
    period["provisional_overage_cents"] = overage.provisional_overage(period, plan)
    db.touch(period)


@bp.post("/hosting-subscriptions/<subscription_id>/usage-records")
@mw.roles_required("PlatformAdmin")
def ingest_usage(subscription_id):
    data = v.body()
    metric = v.req_enum(data, "metric", config.USAGE_METRICS)
    amount_mb = v.req_number(data, "amount_mb", minimum=0)
    recorded_at = v.req_dt(data, "recorded_at")

    subscription = v.get_subscription(subscription_id)
    if subscription["status"] not in METERABLE:
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE")

    period = _open_period_for(subscription, recorded_at)
    if period is None:
        raise ApiError("ERR_USAGE_OUTSIDE_PERIOD")

    record = db.base_record(with_audit=False)
    record.update(
        {
            "subscription_id": subscription["id"],
            "metric": metric,
            "amount_mb": amount_mb,
            "_recorded_at": recorded_at,
        }
    )
    db.usage_records[record["id"]] = record

    plan = db.hosting_plans.get(subscription["plan_id"])
    subscription["bandwidth_used_mb"] = overage.bandwidth_used(period)
    if (
        plan is not None
        and subscription["status"] == "ACTIVE"
        and subscription["bandwidth_used_mb"] > plan["bandwidth_quota_mb"]
    ):
        subscription["status"] = "OVER_QUOTA"
    db.touch(subscription)

    if plan is not None:
        _refresh_period(period, subscription, plan)

    return response.created(usage_record_out(record))


@bp.get("/hosting-subscriptions/<subscription_id>/usage-records")
@mw.roles_required("Registrant", "BillingAdmin", "PlatformAdmin")
def list_usage(subscription_id):
    limit, offset = v.pagination()
    subscription = v.get_subscription(subscription_id)
    mw.require_owner(subscription["account_id"])

    rows = db.ordered(
        db.usage_records, lambda r: r["subscription_id"] == subscription["id"]
    )
    page, total = v.paginate(rows, limit, offset, usage_record_out)
    return response.listing(page, limit, offset, total)


# -------------------------------------------------------- billing periods
@bp.post("/hosting-subscriptions/<subscription_id>/billing-periods")
@mw.roles_required("BillingAdmin")
def create_billing_period(subscription_id):
    data = v.body()
    period_start = v.req_dt(data, "period_start")
    period_end = v.req_dt(data, "period_end")

    subscription = v.get_subscription(subscription_id)
    if subscription["status"] not in METERABLE:
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE")

    for existing in db.billing_periods.values():
        if existing["subscription_id"] != subscription["id"]:
            continue
        if existing["_period_start"] < period_end and period_start < existing["_period_end"]:
            raise ApiError("ERR_BILLING_PERIOD_OVERLAP")

    period = db.base_record()
    period.update(
        {
            "subscription_id": subscription["id"],
            "_period_start": period_start,
            "_period_end": period_end,
            "status": "OPEN",
            "provisional_overage_cents": 0,
            "final_overage_cents": None,
        }
    )
    db.billing_periods[period["id"]] = period
    return response.created(billing_period_out(period))


@bp.get("/hosting-subscriptions/<subscription_id>/billing-periods")
@mw.roles_required("Registrant", "BillingAdmin", "PlatformAdmin")
def list_billing_periods(subscription_id):
    limit, offset = v.pagination()
    status = v.query_enum("status", config.BILLING_PERIOD_STATUSES)

    subscription = v.get_subscription(subscription_id)
    mw.require_owner(subscription["account_id"])

    rows = db.ordered(
        db.billing_periods,
        lambda p: p["subscription_id"] == subscription["id"]
        and (status is None or p["status"] == status),
    )
    page, total = v.paginate(rows, limit, offset, billing_period_out)
    return response.listing(page, limit, offset, total)


@bp.post("/billing-periods/<period_id>/close")
@mw.roles_required("BillingAdmin")
def close_billing_period(period_id):
    period = v.get_billing_period(period_id)
    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_ALREADY_CLOSED")

    subscription = db.subscriptions.get(period["subscription_id"])
    plan = (
        db.hosting_plans.get(subscription["plan_id"]) if subscription is not None else None
    )

    final_cents = overage.final_overage(period, plan) if plan is not None else 0
    period["final_overage_cents"] = final_cents
    period["status"] = "CLOSED"
    db.touch(period)

    if final_cents > 0 and subscription is not None:
        money.create_invoice(
            subscription["account_id"],
            [
                {
                    "item_type": "BANDWIDTH_OVERAGE",
                    "reference_id": period["id"],
                    "description": "Bandwidth overage for the closed billing period",
                    "quantity": 1,
                    "unit_price_cents": final_cents,
                }
            ],
            billing_period_id=period["id"],
        )

    if subscription is not None:
        subscription["bandwidth_used_mb"] = 0
        if subscription["status"] == "OVER_QUOTA":
            subscription["status"] = "ACTIVE"
        db.touch(subscription)

    return response.ok(billing_period_out(period))
