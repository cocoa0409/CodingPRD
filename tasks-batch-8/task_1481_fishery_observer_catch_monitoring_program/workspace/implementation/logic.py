"""Shared business logic: coverage requirement, selection scoring, the
sea-day ledger, cascading reconciliations, cost-recovery invoicing, and
observer capacity screening. Constants and formulas follow the scaffold
calculation table exactly.
"""

import math
from datetime import datetime, timezone
from decimal import Decimal

import store
from core import ApiError, dec, err_forbidden, err_invalid, err_state, parse_dt, round0, round2, round4

# Constants (scaffold section 1.3)
EM_SHARE_CAP = Decimal("0.40")
NOTICE_ALLOCATION_DAYS = 30
W_RECENCY = Decimal("50")
COMPLIANCE_STEP = 10
COMPLIANCE_BASE = 30
PENALTY_WEIGHT = 5
GEAR_PRIORITY_MULTIPLIER = Decimal("1.25")
RECENCY_NULL_DAYS = 365
MAX_DEPLOYMENT_SEA_DAYS = 45
OBSERVER_MAX_COMMITTED_SEA_DAYS = 90
RATE_TIER1_CENTS = 39900
RATE_TIER2_CENTS = 49900
TIER1_LIMIT_DAYS = 20
SURCHARGE_PCT = Decimal("0.037")
SMALL_VESSEL_LENGTH_FT = 40
SMALL_VESSEL_RATE_FACTOR = Decimal("0.5")
FEE_CAP_PCT = Decimal("0.005")
INVOICE_DUE_DAYS = 30
EM_REVIEW_MIN_PCT = Decimal("0.30")
MIN_VERIFIED_COVERAGE = Decimal("0.2000")
MIN_SAMPLE_RATIO = Decimal("0.2000")
MAX_SAMPLE_RATIO = Decimal("1.0000")

CERT_CAPS = {"TRAINEE": 20, "CERTIFIED": 30, "LEAD": 45}

OPEN_DEPLOYMENT_STATUSES = (
    "SCHEDULED", "SAFETY_HOLD", "READY_TO_DEPLOY", "AT_SEA", "RETURNED",
    "EARLY_TERMINATED", "DEBRIEFING", "DATA_REJECTED", "DATA_VALIDATED",
)
ACTIVE_DEPLOYMENT_STATUSES = ("SCHEDULED", "SAFETY_HOLD", "READY_TO_DEPLOY", "AT_SEA")
CANCELLABLE_DEPLOYMENT_STATUSES = ("SCHEDULED", "SAFETY_HOLD", "READY_TO_DEPLOY")
OPEN_EM_TRIP_STATUSES = ("DECLARED", "FOOTAGE_SUBMITTED", "IN_REVIEW", "REVIEWED")
OPEN_ENROLLMENT_STATUSES = ("PENDING_REVIEW", "APPROVED", "ACTIVE", "SUSPENDED")


def days_between(later, earlier):
    """Whole calendar days from `earlier` to `later`."""
    return (later - earlier).days


# ---------------------------------------------------------------------------
# coverage_requirement_calculation (pinned 4-step order)
# ---------------------------------------------------------------------------


def coverage_requirement(effort_days, em_days, coverage_target_pct):
    em_cap_days = math.floor(dec(effort_days) * EM_SHARE_CAP)
    em_credited = min(em_days, em_cap_days)
    covered_base = max(0, effort_days - em_credited)
    required = math.ceil(dec(covered_base) * dec(coverage_target_pct))
    return int(required)


# ---------------------------------------------------------------------------
# vessel_selection_scoring + selection_run_sizing
# ---------------------------------------------------------------------------


def vessel_score(vessel, fishery, plan):
    loed = vessel.get("last_observed_end_date")
    if loed is None:
        recency_days = RECENCY_NULL_DAYS
    else:
        recency_days = days_between(parse_dt(plan["period_start"]), parse_dt(loed))
    recency_component = dec(min(recency_days, RECENCY_NULL_DAYS)) / dec(365) * W_RECENCY
    count = vessel["substantiated_harassment_count"]
    if count == 0:
        compliance_component = dec(COMPLIANCE_BASE)
    else:
        compliance_component = dec(max(0, COMPLIANCE_BASE - COMPLIANCE_STEP * count))
    penalty_component = dec(PENALTY_WEIGHT * vessel["selection_penalty_points"])
    raw = recency_component + compliance_component - penalty_component
    if vessel["gear_type"] == fishery["priority_gear"]:
        raw = raw * GEAR_PRIORITY_MULTIPLIER
    return round4(raw)


def eligible_vessels(plan):
    out = []
    for v in store.db["vessels"].values():
        if v["status"] != "ACTIVE":
            continue
        if v["monitoring_mode"] != "HUMAN_OBSERVER":
            continue
        if v["fishery_id"] != plan["fishery_id"]:
            continue
        op = store.db["operators"].get(v["operator_id"])
        if op is None or op["payment_standing"] != "GOOD":
            continue
        held = any(
            n["vessel_id"] == v["id"]
            and n["coverage_plan_id"] == plan["id"]
            and n["status"] in ("ISSUED", "ACCEPTED")
            for n in store.db["selection_notices"].values()
        )
        if held:
            continue
        out.append(v)
    return out


_AWARE_MIN = datetime.min.replace(tzinfo=timezone.utc)


def rank_vessels(scored):
    """scored: list of (vessel, score). Ranking: score DESC, then
    last_observed_end_date ASC NULLS FIRST, then vessel created_at ASC.
    Vessel.id is never consulted."""
    def key(item):
        v, score = item
        loed = v.get("last_observed_end_date")
        loed_dt = _AWARE_MIN if loed is None else parse_dt(loed)
        null_rank = 0 if loed is None else 1
        return (-score, null_rank, loed_dt, v["created_at"], v["_seq"])
    return sorted(scored, key=key)


# ---------------------------------------------------------------------------
# sea_day_accounting — the notice ledger (PRD 2.9)
# ---------------------------------------------------------------------------


def ledger_reserve(notice, planned):
    notice["remaining_sea_days"] -= planned
    notice["reserved_sea_days"] += planned
    store.touch(notice)


def ledger_reconcile_reschedule(notice, delta):
    notice["remaining_sea_days"] -= delta
    notice["reserved_sea_days"] += delta
    store.touch(notice)


def ledger_release(notice, planned):
    notice["reserved_sea_days"] -= planned
    notice["remaining_sea_days"] += planned
    store.touch(notice)


def ledger_consume(notice, planned, actual):
    notice["reserved_sea_days"] -= planned
    notice["consumed_sea_days"] += actual
    notice["remaining_sea_days"] += (planned - actual)
    store.touch(notice)


# ---------------------------------------------------------------------------
# Deployment screening (PRD 3.4) — temporal -> caps, excluding `exclude_id`
# ---------------------------------------------------------------------------


def check_observer_overlap(observer_id, dep_dt, ret_dt, exclude_id=None):
    for d in store.db["deployments"].values():
        if d["observer_id"] != observer_id or d["id"] == exclude_id:
            continue
        if d["status"] not in ACTIVE_DEPLOYMENT_STATUSES:
            continue
        ex_dep = parse_dt(d["scheduled_departure_date"])
        ex_ret = parse_dt(d["scheduled_return_date"])
        if dep_dt <= ex_ret and ex_dep <= ret_dt:
            raise ApiError("ERR_OBSERVER_OVERLAP", 409,
                           "Observer has an overlapping active deployment")


def check_vessel_turnaround(vessel_id, dep_dt, exclude_id=None):
    for d in store.db["deployments"].values():
        if d["vessel_id"] != vessel_id or d["id"] == exclude_id:
            continue
        if d["status"] not in ACTIVE_DEPLOYMENT_STATUSES:
            continue
        ex_ret = parse_dt(d["scheduled_return_date"])
        gap = days_between(dep_dt, ex_ret) - 1
        if gap < 1:
            raise ApiError("ERR_VESSEL_TURNAROUND_VIOLATION", 409,
                           "Vessel lacks a full in-port day between deployments")


def check_observer_caps(observer, planned, exclude_id=None):
    if planned > observer["max_consecutive_sea_days"]:
        raise ApiError("ERR_OBSERVER_CONSECUTIVE_CAP_EXCEEDED", 422,
                       "planned_sea_days exceeds the observer's consecutive cap")
    committed = 0
    for d in store.db["deployments"].values():
        if d["observer_id"] != observer["id"] or d["id"] == exclude_id:
            continue
        if d["status"] in ACTIVE_DEPLOYMENT_STATUSES:
            committed += d["planned_sea_days"]
    if committed + planned > OBSERVER_MAX_COMMITTED_SEA_DAYS:
        raise ApiError("ERR_OBSERVER_COMMITMENT_CAP_EXCEEDED", 422,
                       "Observer committed sea days would exceed 90")


# ---------------------------------------------------------------------------
# Cascades (PRD 2.10)
# ---------------------------------------------------------------------------


def cancel_deployment_system(deployment, notice):
    """System-path cancellation with day release (no status guard)."""
    ledger_release(notice, deployment["planned_sea_days"])
    deployment["status"] = "CANCELLED"
    store.touch(deployment)


def run_delinquency_cascade(invoice, counters):
    """Invoice -> OVERDUE cascade: operator DELINQUENT, ACTIVE vessels
    SUSPENDED, their open deployments CANCELLED with day release."""
    op = store.db["operators"].get(invoice["operator_id"])
    if op is None:
        return
    if op["payment_standing"] != "DELINQUENT":
        op["payment_standing"] = "DELINQUENT"
        store.touch(op)
        counters["delinquent_operator_count"] += 1
    for v in store.db["vessels"].values():
        if v["operator_id"] != op["id"] or v["status"] != "ACTIVE":
            continue
        v["status"] = "SUSPENDED"
        store.touch(v)
        counters["suspended_vessel_count"] += 1
        for d in store.db["deployments"].values():
            if d["vessel_id"] != v["id"] or d["status"] not in CANCELLABLE_DEPLOYMENT_STATUSES:
                continue
            notice = store.db["selection_notices"].get(d["selection_notice_id"])
            if notice is not None:
                cancel_deployment_system(d, notice)
            else:
                d["status"] = "CANCELLED"
                store.touch(d)
            counters["cancelled_deployment_count"] += 1


def restore_standing_if_clear(operator):
    """Payment/waiver left the operator with zero OVERDUE invoices -> GOOD.
    Vessels deliberately stay SUSPENDED (manual reactivation)."""
    if operator["payment_standing"] != "DELINQUENT":
        return
    has_overdue = any(
        inv["operator_id"] == operator["id"] and inv["status"] == "OVERDUE"
        for inv in store.db["invoices"].values()
    )
    if not has_overdue:
        operator["payment_standing"] = "GOOD"
        store.touch(operator)


def em_activation_cascade(vessel):
    """EM activation: flip monitoring mode, void open notices, cancel their
    pre-boarding deployments with day release."""
    vessel["monitoring_mode"] = "ELECTRONIC_MONITORING"
    store.touch(vessel)
    voided = [
        n for n in store.db["selection_notices"].values()
        if n["vessel_id"] == vessel["id"] and n["status"] in ("ISSUED", "ACCEPTED")
    ]
    voided.sort(key=lambda n: (n["created_at"], n["_seq"]))
    for notice in voided:
        notice["status"] = "VOIDED"
        store.touch(notice)
        deployments = [
            d for d in store.db["deployments"].values()
            if d["selection_notice_id"] == notice["id"]
            and d["status"] in CANCELLABLE_DEPLOYMENT_STATUSES
        ]
        deployments.sort(key=lambda d: (d["created_at"], d["_seq"]))
        for d in deployments:
            cancel_deployment_system(d, notice)


def harassment_early_termination(deployment, notice):
    """Substantiation hop 1: an AT_SEA deployment terminates immediately."""
    clock = store.clock_now()
    departure = parse_dt(deployment["scheduled_departure_date"])
    planned = deployment["planned_sea_days"]
    actual = days_between(clock, departure) + 1
    actual = max(1, min(actual, planned))
    deployment["actual_return_date"] = store.fmt_clock(clock)
    deployment["actual_sea_days"] = actual
    deployment["early_termination_reason"] = "HARASSMENT"
    deployment["status"] = "EARLY_TERMINATED"
    store.touch(deployment)
    ledger_consume(notice, planned, actual)


def maybe_fulfill_notice(notice, closing_deployment_id):
    """Auto-fulfillment at deployment close (PRD 2.10)."""
    if notice["status"] != "ACCEPTED":
        return
    if notice["remaining_sea_days"] != 0:
        return
    for d in store.db["deployments"].values():
        if d["selection_notice_id"] != notice["id"] or d["id"] == closing_deployment_id:
            continue
        if d["status"] not in ("CLOSED", "CANCELLED"):
            return
    notice["status"] = "FULFILLED"
    store.touch(notice)


# ---------------------------------------------------------------------------
# cost_recovery_fee_calculation (PRD 3.9)
# ---------------------------------------------------------------------------


def generate_invoices_for_plan(plan):
    closed = [
        d for d in store.db["deployments"].values()
        if d["coverage_plan_id"] == plan["id"] and d["status"] == "CLOSED"
    ]
    by_vessel = {}
    for d in closed:
        by_vessel.setdefault(d["vessel_id"], []).append(d)

    created_ids = []
    skipped_ids = []
    vessels = sorted(by_vessel.keys(), key=lambda vid: (
        store.db["vessels"][vid]["created_at"], store.db["vessels"][vid]["_seq"]
    ) if vid in store.db["vessels"] else ("", 0))

    for vid in vessels:
        deployments = by_vessel[vid]
        existing = any(
            inv["coverage_plan_id"] == plan["id"] and inv["vessel_id"] == vid
            and inv["status"] not in ("PAID", "WAIVED")
            for inv in store.db["invoices"].values()
        )
        if existing:
            skipped_ids.append(vid)
            continue
        vessel = store.db["vessels"].get(vid)
        deployments.sort(key=lambda d: (parse_dt(d["scheduled_departure_date"]),
                                        d["created_at"], d["_seq"]))
        small = dec(vessel["length_ft"]) < dec(SMALL_VESSEL_LENGTH_FT)
        factor = SMALL_VESSEL_RATE_FACTOR if small else Decimal("1")
        fee_variant = "SMALL_VESSEL" if small else "STANDARD"

        line_items = []
        cumulative = 0
        sea_days_billed = 0
        for d in deployments:
            days = d["actual_sea_days"]
            tier1_days = max(0, min(days, TIER1_LIMIT_DAYS - cumulative))
            tier2_days = days - tier1_days
            cumulative += days
            sea_days_billed += days
            subtotal = (dec(tier1_days * RATE_TIER1_CENTS)
                        + dec(tier2_days * RATE_TIER2_CENTS)) * factor
            subtotal = int(subtotal)  # rates are multiples of 100 -> exact cents
            line_total = int(round0(dec(subtotal) * (Decimal("1") + SURCHARGE_PCT)))
            line_items.append({
                "deployment_id": d["id"],
                "days": days,
                "tier1_days": tier1_days,
                "tier2_days": tier2_days,
                "line_subtotal_cents": subtotal,
                "line_total_cents": line_total,
            })

        amount_due = sum(li["line_total_cents"] for li in line_items)
        fee_cap_applied = False
        revenue = vessel.get("declared_annual_revenue_cents")
        if revenue is not None:
            cap = math.floor(dec(revenue) * FEE_CAP_PCT)
            if amount_due > cap:
                amount_due = int(cap)
                fee_cap_applied = True

        invoice = store.new_entity({
            "coverage_plan_id": plan["id"],
            "vessel_id": vid,
            "operator_id": vessel["operator_id"],
            "fee_variant": fee_variant,
            "sea_days_billed": sea_days_billed,
            "line_items": line_items,
            "amount_due_cents": amount_due,
            "fee_cap_applied": fee_cap_applied,
            "amount_paid_cents": 0,
            "amount_adjusted_cents": 0,
            "amount_outstanding_cents": amount_due,
            "issued_by_user_id": None,
            "issue_date": None,
            "due_date": None,
            "status": "DRAFT",
        })
        store.db["invoices"][invoice["id"]] = invoice
        created_ids.append(invoice["id"])

    return created_ids, skipped_ids


def invoice_outstanding(invoice):
    return (invoice["amount_due_cents"] + invoice["amount_adjusted_cents"]
            - invoice["amount_paid_cents"])
