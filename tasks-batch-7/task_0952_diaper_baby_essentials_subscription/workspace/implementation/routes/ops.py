"""The logical clock and the daily batch (PRD 2.5, 3.11)."""

from flask import Blueprint

import calc
import constants as C
import services
import shapes
import store
from auth import api
from envelope import ok
from store import db, now, touch

bp = Blueprint("ops", __name__)


@api(bp, "POST", "/_clock/set_current_utc", ["OpsAdmin"])
def clock_set():
    parsed = shapes.validate(shapes.body(), [
        shapes.field("to_iso8601", required=True, kind="instant"),
    ])
    raw = parsed["to_iso8601"]
    store.set_clock(store.parse_instant(raw), raw)
    # The caller's own instant is echoed back VERBATIM (case (b) of the
    # timestamp rule); before the first call it reads exactly DEFAULT_CLOCK_UTC.
    return ok({"current_utc": store.clock_raw()})


@api(bp, "POST", "/_ops/run-daily-jobs", ["OpsAdmin"])
def run_daily_jobs():
    expired_credits = 0
    for credit in store.by_created(list(db.credits.values())):
        if credit["status"] in ("AVAILABLE", "PARTIALLY_CONSUMED") and \
                credit["expires_at"] <= now():
            services.forfeit_credit(credit, "EXPIRED")
            services.recompute_account_estimate(credit["account_id"])
            expired_credits += 1

    expired_points = 0
    for wallet in store.by_created(list(db.loyalty_accounts.values())):
        written = services.points_expiry_sweep(wallet)
        if written:
            touch(wallet)
        expired_points += written

    expired_referrals = 0
    for referral in store.by_created(list(db.referrals.values())):
        if referral["status"] == "PENDING" and now() > referral["expires_at"]:
            referral["status"] = "EXPIRED"
            touch(referral)
            expired_referrals += 1

    activated_pauses = 0
    ended_pauses = 0
    today = store.today()
    for record in store.by_created(list(db.pause_records.values())):
        sub = db.subscriptions.get(record["subscription_id"])
        if sub is None:
            continue
        if record["status"] == "SCHEDULED" and today >= record["start_date"]:
            record["status"] = "ACTIVE"
            touch(record)
            if sub["lifecycle_state"] == "ACTIVE":
                sub["lifecycle_state"] = "PAUSED"
                touch(sub)
            activated_pauses += 1
    for record in store.by_created(list(db.pause_records.values())):
        sub = db.subscriptions.get(record["subscription_id"])
        if sub is None:
            continue
        if record["status"] == "ACTIVE" and today > record["end_date"]:
            record["status"] = "ENDED"
            record["actual_end_date"] = record["end_date"]
            consumed = (record["actual_end_date"] - record["start_date"]).days + 1
            record["consumed_days"] = consumed
            touch(record)
            if sub["lifecycle_state"] == "PAUSED":
                sub["lifecycle_state"] = "ACTIVE"
            if sub["anchor_date"] is not None:
                sub["anchor_date"] = store.plus_days(sub["anchor_date"], consumed)
            services.recompute_pause_days(sub)
            touch(sub)
            ended_pauses += 1

    delinquent_subscriptions = 0
    for sub in store.by_created(list(db.subscriptions.values())):
        if sub["billing_state"] != "PAST_DUE":
            continue
        overdue = False
        for cycle in services.cycles_of_subscription(sub["id"]):
            if cycle["payment_status"] != "UNCHARGED":
                continue
            if cycle["ship_date"] is None:
                continue
            elapsed = (now() - cycle["ship_date"]).total_seconds()
            if elapsed > C.DELINQUENCY_GRACE_DAYS * 86400:
                overdue = True
                break
        if overdue:
            sub["billing_state"] = "DELINQUENT"
            touch(sub)
            delinquent_subscriptions += 1

    return ok({
        "expired_credits": expired_credits,
        "expired_points": expired_points,
        "expired_referrals": expired_referrals,
        "activated_pauses": activated_pauses,
        "ended_pauses": ended_pauses,
        "delinquent_subscriptions": delinquent_subscriptions,
    })
