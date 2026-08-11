"""Ops endpoints: daily sweep and test-driving clock."""

from datetime import timedelta

from flask import Blueprint, request

import errors
import validation as v
from db import store, clock, touch, parse_datetime
from middleware import require_roles
from response import success_object

bp = Blueprint("ops", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles(["ClinicAdmin"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"to_iso8601"})
    to_iso8601 = v.req_datetime(body, "to_iso8601")
    clock.set(to_iso8601)
    return success_object({"current_utc": clock.now_iso()})


@bp.post("/api/ops/run_daily")
def run_daily():
    require_roles(["ClinicAdmin"])
    now = clock.now()

    expired_order_ids = []
    overdue_loan_ids = []
    past_due_subscription_ids = []
    suspended_subscription_ids = []
    expired_authorization_ids = []

    def by_created(items):
        return sorted(items, key=lambda e: (e["created_at"], e["id"]))

    # 1. Device orders: TRIAL + ACTIVE + now > trial_ends_at -> EXPIRED
    for order in by_created(list(store.device_orders.values())):
        if (order["fulfillment_type"] == "TRIAL" and order["status"] == "ACTIVE"
                and order.get("trial_ends_at") is not None
                and now > parse_datetime(order["trial_ends_at"])):
            order["status"] = "EXPIRED"
            touch(order)
            expired_order_ids.append(order["id"])

    # 2. Loan agreements: ACTIVE + now > due_at -> OVERDUE
    for loan in by_created(list(store.loan_agreements.values())):
        if loan["status"] == "ACTIVE" and now > parse_datetime(loan["due_at"]):
            loan["status"] = "OVERDUE"
            days = int((now - parse_datetime(loan["due_at"])).total_seconds() // 86400)
            loan["overdue_days"] = days if days > 0 else 0
            touch(loan)
            overdue_loan_ids.append(loan["id"])

    # 3. Subscriptions: ACTIVE + now > period_end -> PAST_DUE (past_due_since = period_end)
    for sub in by_created(list(store.subscriptions.values())):
        if sub["status"] == "ACTIVE" and now > parse_datetime(sub["period_end"]):
            sub["status"] = "PAST_DUE"
            sub["past_due_since"] = sub["period_end"]
            touch(sub)
            past_due_subscription_ids.append(sub["id"])

    # 4. Subscriptions: PAST_DUE + now > past_due_since + 14 days -> SUSPENDED
    for sub in by_created(list(store.subscriptions.values())):
        if sub["status"] == "PAST_DUE" and sub.get("past_due_since") is not None:
            threshold = parse_datetime(sub["past_due_since"]) + timedelta(days=14)
            if now > threshold:
                sub["status"] = "SUSPENDED"
                touch(sub)
                suspended_subscription_ids.append(sub["id"])

    # 5. Funding authorizations: APPROVED + now > valid_until -> EXPIRED
    for auth in by_created(list(store.funding_authorizations.values())):
        if auth["status"] == "APPROVED" and now > parse_datetime(auth["valid_until"]):
            auth["status"] = "EXPIRED"
            touch(auth)
            expired_authorization_ids.append(auth["id"])

    return success_object({
        "expired_order_ids": expired_order_ids,
        "overdue_loan_ids": overdue_loan_ids,
        "past_due_subscription_ids": past_due_subscription_ids,
        "suspended_subscription_ids": suspended_subscription_ids,
        "expired_authorization_ids": expired_authorization_ids,
    })
