"""Test-driving endpoints: logical clock and billing simulation."""
from flask import Blueprint

import clock
import db as _db
from db import db, touch
from errors import invalid_request, invalid_state
from helpers import body, get_or_404, parse_dt, public, req_enum, req_str
from middleware import require
from response import success
from services import (advance_billing, recompute_plan_count,
                      run_scheduled_transitions)

bp = Blueprint("admin", __name__)


def _fmt_z(dt):
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return "%s.%03dZ" % (base, dt.microsecond // 1000)
    return base + "Z"


@bp.post("/_clock/set_current_utc")
def set_clock():
    require(["PlatformAdmin"])
    data = body()
    raw = req_str(data, "to_iso8601")
    dt = parse_dt(raw)
    clock.set_now(dt)
    run_scheduled_transitions()
    return success({"now": _fmt_z(clock.now())})


@bp.post("/_billing/simulate")
def billing_simulate():
    require(["PlatformAdmin"])
    data = body()
    sub_id = req_str(data, "club_subscription_id")
    outcome = req_enum(data, "outcome", {"SUCCEEDED", "FAILED"})
    sub = get_or_404(db["club_subscriptions"], sub_id)
    plan = db["club_plans"].get(sub["plan_id"])
    if outcome == "SUCCEEDED":
        if sub["status"] not in ("ACTIVE", "PAST_DUE", "TRIALING"):
            raise invalid_state("Subscription state does not permit billing")
        sub["failed_billing_count"] = 0
        if plan is not None:
            advance_billing(sub, plan)
        if sub["status"] in ("PAST_DUE", "TRIALING"):
            sub["status"] = "ACTIVE"
        touch(sub)
        if plan is not None:
            recompute_plan_count(plan)
    else:  # FAILED
        if sub["status"] not in ("ACTIVE", "PAST_DUE"):
            raise invalid_state("Billing failure requires ACTIVE or PAST_DUE subscription")
        sub["failed_billing_count"] += 1
        if sub["failed_billing_count"] >= 3:
            sub["status"] = "EXPIRED"
        else:
            sub["status"] = "PAST_DUE"
        touch(sub)
        if plan is not None:
            recompute_plan_count(plan)
    return success(public(sub))
