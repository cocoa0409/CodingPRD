"""Cohort snapshots and the logical clock (PRD §3.9, §2.4)."""
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint

import constants as K
import serializers as S
import validation as V
from db import base_record, store
from middleware import auth
from response import created, ok
from services import calc

bp = Blueprint("analytics", __name__)


def _month_bounds(cohort_month):
    year = int(cohort_month[:4])
    month = int(cohort_month[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


@bp.post("/retention-cohort-snapshots")
@auth("RetentionSpecialist", "PlatformAdmin")
def create_snapshot():
    data = V.body()
    cohort_month = V.cohort_month(data)
    variant = V.req_enum(data, "ltv_variant", K.LTV_VARIANTS)
    channel = V.opt_enum(data, "acquisition_channel", K.ACQUISITION_CHANNELS)
    plan_code = V.opt_str(data, "plan_code")
    bucket = V.opt_enum(data, "tenure_bucket", K.TENURE_BUCKETS)

    start, end = _month_bounds(cohort_month)
    members = []
    for subscriber in store.subscribers.values():
        first = subscriber.get("first_subscribed_at")
        if first is None or not (start <= first < end):
            continue
        if channel is not None and subscriber["acquisition_channel"] != channel:
            continue
        if bucket is not None and calc.tenure_bucket_now(subscriber) != bucket:
            continue
        if plan_code is not None:
            subs = calc.subscriptions_of(subscriber["id"])
            if not subs:
                continue
            plan = store.plans.get(subs[0]["plan_id"])
            if plan is None or plan["code"] != plan_code:
                continue
        members.append(subscriber)

    member_count = len(members)
    retained = 0
    voluntary = 0
    involuntary = 0
    ltv_total = 0
    for subscriber in members:
        subs = calc.subscriptions_of(subscriber["id"])
        if any(s["lifecycle_state"] in ("ACTIVE", "PAUSED", "PENDING_CANCEL") for s in subs):
            retained += 1
        if subscriber["churn_type"] == "VOLUNTARY":
            voluntary += 1
        elif subscriber["churn_type"] == "INVOLUNTARY":
            involuntary += 1
        ltv_total += (calc.realized_ltv(subscriber) if variant == "REALIZED"
                      else calc.projected_ltv(subscriber))

    rec = base_record(versioned=False)
    rec.update({
        "cohort_month": cohort_month,
        "acquisition_channel": channel,
        "plan_code": plan_code,
        "tenure_bucket": bucket,
        "ltv_variant": variant,
        "member_count": member_count,
        "retained_count": retained,
        "churned_voluntary_count": voluntary,
        "churned_involuntary_count": involuntary,
        "retention_rate": calc.ratio4(retained, member_count),
        "mean_ltv_cents": (calc.half_up_int(Decimal(ltv_total) / Decimal(member_count))
                           if member_count else 0),
        "computed_at": store.now(),
    })
    store.cohort_snapshots[rec["id"]] = rec
    return created(S.snapshot(rec))


@bp.get("/retention-cohort-snapshots/<snapshot_id>")
@auth("PlatformAdmin", "RetentionSpecialist", "ComplianceOfficer")
def read_snapshot(snapshot_id):
    return ok(S.snapshot(V.must_exist("cohort_snapshots", snapshot_id)))


@bp.post("/_clock/set_current_utc")
@auth("PlatformAdmin")
def set_clock():
    data = V.body()
    instant = V.req_dt(data, "to_iso8601")
    store.set_clock(instant)
    return ok({})
