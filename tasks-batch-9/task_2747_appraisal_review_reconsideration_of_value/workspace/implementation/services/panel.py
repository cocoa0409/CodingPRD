"""Appraiser performance scoring, AMC breach tallies and both panel cascades."""

from datetime import timedelta
from decimal import Decimal

import db
from validate import bps_of, rhu
from services import constants as C


# ------------------------------------------------------------- appraiser side
def refresh_appraiser_counters(appraiser):
    aid = appraiser["id"]
    open_count = 0
    completed = 0
    for order in db.escalation_orders.values():
        if order.get("assigned_appraiser_id") != aid:
            continue
        if order["status"] in ("ASSIGNED", "REASSIGNMENT_REQUIRED"):
            open_count += 1
        elif order["status"] == "COMPLETED":
            completed += 1
    appraiser["open_assignment_count"] = open_count
    appraiser["completed_assignment_count"] = completed
    appraiser["panel_membership_count"] = sum(
        1 for m in db.panel_memberships.values()
        if m["appraiser_id"] == aid and m["status"] == "ACTIVE")
    db.touch(appraiser)


def _score_variant(appraiser, window_start):
    aid = appraiser["id"]
    windowed = [a for a in db.appraisals.values()
                if a["appraiser_id"] == aid
                and a["review_status"] != "SUPERSEDED"
                and (window_start is None or a["created_at"] >= window_start)]
    ids = set(a["id"] for a in windowed)
    revisions = [r for r in db.value_revisions.values()
                 if r["appraisal_id"] in ids
                 and not r["is_compensating"]
                 and (window_start is None or r["created_at"] >= window_start)]
    total = len(windowed)
    rate = 0 if total == 0 else bps_of(len(revisions), total)
    score = (C.BASE_PERFORMANCE_SCORE_BPS
             - rhu(C.REVISION_RATE_WEIGHT * Decimal(rate))
             - C.SUBSTANTIATED_BIAS_PENALTY * appraiser["substantiated_bias_count"]
             - C.SLA_MISS_PENALTY * appraiser["sla_miss_count"])
    score = max(0, min(C.BASE_PERFORMANCE_SCORE_BPS, score))
    return total, rate, score


def recompute_performance(appraiser, cascade=True):
    """Recompute both variants.  ROLLING_12M persists the operational fields
    and is the only variant that drives the panel cascade; LIFETIME is audit
    only."""
    window_start = db.now() - timedelta(days=C.ROLLING_WINDOW_DAYS)
    total, rate, rolling = _score_variant(appraiser, window_start)
    _, _, lifetime = _score_variant(appraiser, None)
    appraiser["total_appraisal_count"] = total
    appraiser["revision_rate_bps"] = rate
    appraiser["performance_score_bps"] = rolling
    appraiser["lifetime_performance_score_bps"] = lifetime
    refresh_appraiser_counters(appraiser)
    if cascade:
        apply_appraiser_cascade(appraiser)


def apply_appraiser_cascade(appraiser):
    """Automatic panel standing edges.  The cascade never reaches REMOVED."""
    score = appraiser["performance_score_bps"]
    status = appraiser["panel_status"]
    moved = False
    if score < C.SUSPENSION_THRESHOLD_BPS and status in ("ACTIVE", "PROBATION"):
        appraiser["panel_status"] = "SUSPENDED"
        moved = True
    elif (C.SUSPENSION_THRESHOLD_BPS <= score < C.PROBATION_THRESHOLD_BPS
          and status == "ACTIVE"):
        appraiser["panel_status"] = "PROBATION"
        appraiser["probation_started_at"] = db.now()
        moved = True
    if moved:
        db.touch(appraiser)
        flag_second_appraisal_orders(appraiser["id"])
    return moved


def flag_second_appraisal_orders(appraiser_id):
    """Every ASSIGNED second-appraisal order held by the appraiser becomes
    REASSIGNMENT_REQUIRED."""
    for order in db.ordered(db.escalation_orders):
        if (order.get("assigned_appraiser_id") == appraiser_id
                and order["status"] == "ASSIGNED"
                and order["escalation_type"] == "SECOND_APPRAISAL"):
            order["status"] = "REASSIGNMENT_REQUIRED"
            db.bump(order)


def flag_all_orders_for_removal(appraiser_id):
    """Explicit removal releases every open order regardless of type."""
    for order in db.ordered(db.escalation_orders):
        if (order.get("assigned_appraiser_id") == appraiser_id
                and order["status"] in ("ASSIGNED", "REASSIGNMENT_REQUIRED")):
            order["status"] = "REASSIGNMENT_REQUIRED"
            db.bump(order)


# ------------------------------------------------------------------- amc side
def refresh_amc_counters(amc):
    amc_id = amc["id"]
    open_disputes = 0
    breaches = 0
    for case in db.dispute_cases.values():
        if case["amc_id"] != amc_id:
            continue
        if case["status"] == "OPEN":
            open_disputes += 1
        if case.get("responded_late"):
            breaches += 1
        if case["status"] == "RESOLVED_BY_DEFAULT":
            breaches += 1
    amc["open_dispute_count"] = open_disputes
    amc["sla_breach_count"] = breaches
    amc["ytd_escalation_spend_cents"] = escalation_spend(amc_id)
    db.touch(amc)


def escalation_spend(amc_id, exclude_order_id=None):
    total = 0
    for order in db.escalation_orders.values():
        if order["amc_id"] != amc_id:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order["status"] in ("ASSIGNED", "REASSIGNMENT_REQUIRED", "COMPLETED"):
            total += order.get("total_cost_cents") or 0
    return total


def apply_amc_cascade(amc):
    """Evaluated after every breach, so ACTIVE reaches SUSPENDED only through
    PROBATION."""
    breaches = amc["sla_breach_count"]
    if breaches >= C.AMC_SUSPENSION_BREACHES and amc["panel_status"] == "PROBATION":
        amc["panel_status"] = "SUSPENDED"
        db.touch(amc)
    elif (C.AMC_PROBATION_BREACHES <= breaches < C.AMC_SUSPENSION_BREACHES
          and amc["panel_status"] == "ACTIVE"):
        amc["panel_status"] = "PROBATION"
        db.touch(amc)
