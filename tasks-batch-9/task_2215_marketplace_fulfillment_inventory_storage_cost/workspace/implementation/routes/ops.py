"""Operational endpoints: storage billing runs and the logical clock."""
from flask import Blueprint

import calc
import clock
import db as store
import response
import validate
from db import db, mark_created, set_field
from middleware import require_roles
from routes.common import finish

bp = Blueprint("ops", __name__)

CLOSABLE_STATUSES = ("RECEIVED_COMPLETE", "PARTIALLY_RECEIVED")
PLAN_CLOSURE_GRACE_DAYS = 30


@bp.post("/fulfillment/storage-billing-runs")
@require_roles("MarketplaceAdmin")
def create_billing_run():
    data = validate.body()
    validate.opt_str(data, "run_note")

    now = clock.now()

    # Utilization (and every other derived figure) is refreshed at the start of
    # the run so the downgrade gate below reads a current ratio.
    calc.recompute_all()

    db.billing_run_sequence += 1
    sequence = db.billing_run_sequence

    eligible = [lot for lot in db.lots.values()
                if lot["lot_status"] in store.LOT_LIVE_STATUSES]
    eligible.sort(key=lambda l: (l["first_received_at"], l["created_at"], l["_seq"]))

    assessment_count = 0
    total_assessed_cents = 0
    for lot in eligible:
        listing = db.listings.get(lot["sku_listing_id"])
        fc = db.fcs.get(lot["fulfillment_center_id"])
        if listing is None or fc is None:
            continue
        row = calc.assess_lot(lot, listing, fc, now, sequence)
        db.assessments[row["id"]] = row
        mark_created(row)
        assessment_count += 1
        total_assessed_cents += row["total_fee_cents"]

    # Lot pools did not move, but aged_bucket may have: refresh the rollups so
    # the utilization ratio read by the downgrade gate is current.
    calc.recompute_all()

    downgraded_quota_count = 0
    for seller in db.sellers.values():
        if seller["storage_utilization_ratio"] <= 1:
            continue
        quota = store.active_quota(seller["id"])
        if quota is None:
            continue
        set_field(quota, "capacity_tier_downgrade_steps",
                  quota["capacity_tier_downgrade_steps"] + 1)
        calc.run_iprs(quota)
        downgraded_quota_count += 1

    expired_quota_count = 0
    for quota in db.quotas.values():
        if quota["status"] == "ACTIVE" and quota["period_end"] <= now:
            set_field(quota, "status", "EXPIRED")
            expired_quota_count += 1

    closed_plan_count = 0
    for plan in db.plans.values():
        if plan["status"] not in CLOSABLE_STATUSES:
            continue
        if clock.plus_days(plan["appointment_window_end"], PLAN_CLOSURE_GRACE_DAYS) > now:
            continue
        set_field(plan, "status", "CLOSED")
        set_field(plan, "allocated_units", 0)
        closed_plan_count += 1

    summary = {
        "billing_run_sequence": sequence,
        "assessment_count": assessment_count,
        "total_assessed_cents": total_assessed_cents,
        "downgraded_quota_count": downgraded_quota_count,
        "expired_quota_count": expired_quota_count,
        "closed_plan_count": closed_plan_count,
    }
    return finish(lambda: summary, 201)


@bp.post("/_clock/set_current_utc")
@require_roles("MarketplaceAdmin")
def set_clock():
    data = validate.body()
    target = validate.req_dt(data, "to_iso8601")
    current = clock.set_now(target)
    return response.object_response({"current_utc": clock.fmt(current)}, 200)
