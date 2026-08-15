"""Derived balances, serializers, and entity mutation bookkeeping.

Design: source-of-truth rows are stored; every derived balance named in the PRD
(committed / capitalized / contra on programs, actuals / AFUDC / CWIP / variance
posture / approved estimate / estimate_seq on work orders, accumulated
depreciation on units, remaining on regulatory assets, available on programs) is
recomputed from the ledger at read time, so period close / reopen compensation
and cascades can never drift. Snapshot fields (gross_cwip_cents,
capitalizable_total_cents, ciac_applied_cents, cancel_writeoff_disposition) and
the event-based expense_writeoff_cents counter are stored on the entity.

Every mutation of an entity — direct edit or derived-field recompute — refreshes
updated_at and increments version exactly once per request per entity (PRD 2.4,
2.10). The three ledger-entry collections carry only id + created_at (PRD 2.4).
"""
from db import db, next_seq
from util import now_ts, new_id

# Work-order statuses
WO_NON_TERMINAL_FOR_PROGRAM_CLOSE = (
    "DRAFT", "SUBMITTED", "RETURNED", "AUTHORIZED", "IN_PROGRESS", "SUSPENDED", "COMPLETED",
)
WO_COMMITTED_STATUSES = ("AUTHORIZED", "IN_PROGRESS", "SUSPENDED", "COMPLETED")
WO_AFUDC_ELIGIBLE_STATUSES = ("AUTHORIZED", "IN_PROGRESS", "SUSPENDED")
WO_CHARGEABLE_STATUSES = ("AUTHORIZED", "IN_PROGRESS")
WO_ESTIMABLE_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "AUTHORIZED", "IN_PROGRESS", "SUSPENDED")
WO_DECIDABLE_STATUSES = ("SUBMITTED", "AUTHORIZED", "IN_PROGRESS", "SUSPENDED")
WO_CANCELLABLE_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "AUTHORIZED", "IN_PROGRESS", "SUSPENDED")
WO_CIAC_PLEDGEABLE_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "AUTHORIZED", "IN_PROGRESS", "SUSPENDED")
WO_CIAC_RECEIVABLE_STATUSES = (
    "DRAFT", "SUBMITTED", "RETURNED", "AUTHORIZED", "IN_PROGRESS", "SUSPENDED", "COMPLETED",
)

VARIANCE_BLOCK_PCT = 110
REESTIMATE_CONTROLLER_PCT = 10
AUTHORIZE_CONTROLLER_THRESHOLD_CENTS = 10_000_000
CLOSEOUT_TOLERANCE_PCT = 15
CIAC_FORFEIT_PCT = 10


# ---------------------------------------------------------------------------
# Entity bookkeeping
# ---------------------------------------------------------------------------

def new_record(extra_common=True):
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": now_ts(),
        "_seq": next_seq(),
    }
    if extra_common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """PRD 2.10: any mutation (direct or derived-field recompute) refreshes
    updated_at and increments version by exactly one."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Derived balances — work orders
# ---------------------------------------------------------------------------

def wo_charges(work_order_id):
    return [c for c in db["cost_charges"].values() if c["work_order_id"] == work_order_id]


def wo_actual_direct_cents(work_order_id) -> int:
    """Sum of total_cents over ALL charge rows of the order (an ORIGINAL row
    stays counted after flipping to REVERSED; its compensating REVERSAL row
    carries the exact negation). Excludes AFUDC."""
    return sum(c["total_cents"] for c in wo_charges(work_order_id))


def wo_afudc_total_cents(work_order_id) -> int:
    return sum(
        e["amount_cents"]
        for e in db["afudc_entries"].values()
        if e["work_order_id"] == work_order_id and e["status"] == "ACCRUED"
    )


def wo_cwip_cents(work_order_id) -> int:
    return wo_actual_direct_cents(work_order_id) + wo_afudc_total_cents(work_order_id)


def wo_estimates(work_order_id):
    return [e for e in db["estimates"].values() if e["work_order_id"] == work_order_id]


def wo_estimate_seq(work_order_id) -> int:
    seqs = [e["estimate_seq"] for e in wo_estimates(work_order_id)]
    return max(seqs) if seqs else 0


def wo_approved_estimate(work_order_id):
    for e in wo_estimates(work_order_id):
        if e["status"] == "APPROVED":
            return e
    return None


def wo_approved_estimate_cents(work_order_id):
    est = wo_approved_estimate(work_order_id)
    return est["estimated_cost_cents"] if est is not None else None


def wo_variance_posture(work_order_id) -> str:
    """Strictly-greater 110% rule, exact integer comparison (PRD 3.5)."""
    approved = wo_approved_estimate_cents(work_order_id)
    if approved is None:
        return "WITHIN_TOLERANCE"
    if wo_actual_direct_cents(work_order_id) * 100 > approved * VARIANCE_BLOCK_PCT:
        return "RE_ESTIMATE_REQUIRED"
    return "WITHIN_TOLERANCE"


# ---------------------------------------------------------------------------
# Derived balances — programs
# ---------------------------------------------------------------------------

def program_work_orders(program_id):
    return [w for w in db["work_orders"].values() if w["program_id"] == program_id]


def program_committed_cents(program_id) -> int:
    total = 0
    for wo in program_work_orders(program_id):
        if wo["status"] in WO_COMMITTED_STATUSES:
            ap = wo_approved_estimate_cents(wo["id"])
            if ap is not None:
                total += ap
    return total


def program_capitalized_cents(program_id) -> int:
    total = 0
    for wo in program_work_orders(program_id):
        if wo["status"] == "CLOSED" and wo.get("capitalizable_total_cents") is not None:
            total += wo["capitalizable_total_cents"]
    return total


def program_ciac_contra_balance_cents(program) -> int:
    """GROSS_WITH_CONTRA only: CIAC applied at closeouts minus POSTED
    depreciation contra credits (reversed entries excluded automatically)."""
    if program.get("ciac_method") != "GROSS_WITH_CONTRA":
        return 0
    pid = program["id"]
    applied = 0
    for wo in program_work_orders(pid):
        if wo["status"] == "CLOSED" and wo.get("ciac_applied_cents"):
            applied += wo["ciac_applied_cents"]
    credits = 0
    for unit in db["fixed_asset_units"].values():
        wo = db["work_orders"].get(unit["work_order_id"])
        if wo is None or wo["program_id"] != pid:
            continue
        credits += sum(
            e["ciac_contra_credit_cents"]
            for e in db["depreciation_entries"].values()
            if e["fixed_asset_unit_id"] == unit["id"] and e["status"] == "POSTED"
        )
    return applied - credits


def program_available_cents(program) -> int:
    return program["authorized_amount_cents"] - program_committed_cents(program["id"])


# ---------------------------------------------------------------------------
# Derived balances — units and regulatory assets
# ---------------------------------------------------------------------------

def unit_accumulated_depreciation_cents(unit_id) -> int:
    return sum(
        e["amount_cents"]
        for e in db["depreciation_entries"].values()
        if e["fixed_asset_unit_id"] == unit_id and e["status"] == "POSTED"
    )


def asset_posted_amortization(reg_asset_id):
    return [
        e for e in db["amortization_entries"].values()
        if e["regulatory_asset_id"] == reg_asset_id and e["status"] == "POSTED"
    ]


def asset_remaining_cents(asset) -> int:
    posted = sum(e["amount_cents"] for e in asset_posted_amortization(asset["id"]))
    return asset["original_cents"] - posted


# ---------------------------------------------------------------------------
# Misc lookups
# ---------------------------------------------------------------------------

def wo_ciac_agreements(work_order_id):
    items = [a for a in db["ciac_agreements"].values() if a["work_order_id"] == work_order_id]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return items


def wo_ciac_received_to_date(work_order_id) -> int:
    """CIAC-financed CWIP earns no AFUDC: receipts in RECEIVED or APPLIED."""
    return sum(
        a["received_cents"] or 0
        for a in wo_ciac_agreements(work_order_id)
        if a["status"] in ("RECEIVED", "APPLIED")
    )


def current_open_period():
    """The single AccountingPeriod in OPEN or REOPENED, or None."""
    for p in db["accounting_periods"].values():
        if p["status"] in ("OPEN", "REOPENED"):
            return p
    return None


def period_containing(d):
    for p in db["accounting_periods"].values():
        if p["_start"] <= d <= p["_end"]:
            return p
    return None


def latest_period():
    periods = list(db["accounting_periods"].values())
    if not periods:
        return None
    return max(periods, key=lambda p: p["_seq"])


def resolve_overhead_rate(cost_type, order_type, charge_date):
    """Unique OverheadSchedule row covering (cost_type, order_type, charge_date)
    under the half-open [effective_from, effective_to) convention."""
    for s in db["overhead_schedules"].values():
        if s["cost_type"] != cost_type or s["order_type"] != order_type:
            continue
        if s["_from"] <= charge_date and (s["_to"] is None or charge_date < s["_to"]):
            return s
    return None


def estimate_routing_tier(estimated_cost_cents, work_order_id) -> str:
    """Decision-time tier: no current approved estimate -> SUPERVISOR; otherwise
    |new - current| * 100 >= current * 10 -> CONTROLLER (inclusive boundary)."""
    current = wo_approved_estimate_cents(work_order_id)
    if current is None:
        return "SUPERVISOR"
    if abs(estimated_cost_cents - current) * 100 >= current * REESTIMATE_CONTROLLER_PCT:
        return "CONTROLLER"
    return "SUPERVISOR"


# ---------------------------------------------------------------------------
# Serializers (stored fields + derived fields; internal "_*" keys dropped)
# ---------------------------------------------------------------------------

def serialize_program(p):
    committed = program_committed_cents(p["id"])
    return {
        "id": p["id"],
        "code": p["code"],
        "fiscal_year": p["fiscal_year"],
        "authorized_amount_cents": p["authorized_amount_cents"],
        "afudc_debt_rate_pct": p["afudc_debt_rate_pct"],
        "afudc_equity_rate_pct": p["afudc_equity_rate_pct"],
        "afudc_debt_weight_pct": p["afudc_debt_weight_pct"],
        "afudc_method": p["afudc_method"],
        "ciac_method": p["ciac_method"],
        "status": p["status"],
        "committed_amount_cents": committed,
        "capitalized_actual_cents": program_capitalized_cents(p["id"]),
        "expense_writeoff_cents": p["expense_writeoff_cents"],
        "ciac_contra_balance_cents": program_ciac_contra_balance_cents(p),
        "available_amount_cents": p["authorized_amount_cents"] - committed,
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_catalog(c):
    return {
        "id": c["id"],
        "asset_class": c["asset_class"],
        "standard_cost_cents": c["standard_cost_cents"],
        "annual_depreciation_rate_pct": c["annual_depreciation_rate_pct"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_schedule(s):
    return {
        "id": s["id"],
        "cost_type": s["cost_type"],
        "order_type": s["order_type"],
        "rate_pct": s["rate_pct"],
        "effective_from": s["effective_from"],
        "effective_to": s["effective_to"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_period(p):
    return {
        "id": p["id"],
        "fiscal_year": p["fiscal_year"],
        "period_no": p["period_no"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "status": p["status"],
        "closed_at": p["closed_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_work_order(w):
    wid = w["id"]
    actual = wo_actual_direct_cents(wid)
    afudc = wo_afudc_total_cents(wid)
    return {
        "id": wid,
        "program_id": w["program_id"],
        "order_type": w["order_type"],
        "title": w["title"],
        "status": w["status"],
        "variance_posture": wo_variance_posture(wid),
        "estimate_seq": wo_estimate_seq(wid),
        "approved_estimate_cents": wo_approved_estimate_cents(wid),
        "actual_direct_cents": actual,
        "afudc_total_cents": afudc,
        "cwip_cents": actual + afudc,
        "in_service_date": w["in_service_date"],
        "in_service_period_id": w["in_service_period_id"],
        "gross_cwip_cents": w["gross_cwip_cents"],
        "ciac_applied_cents": w["ciac_applied_cents"],
        "capitalizable_total_cents": w["capitalizable_total_cents"],
        "cancel_writeoff_disposition": w["cancel_writeoff_disposition"],
        "created_by_user_id": w["created_by_user_id"],
        "authorized_by_user_id": w["authorized_by_user_id"],
        "completed_by_user_id": w["completed_by_user_id"],
        "closed_by_user_id": w["closed_by_user_id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_estimate(e):
    return {
        "id": e["id"],
        "work_order_id": e["work_order_id"],
        "estimate_seq": e["estimate_seq"],
        "estimated_cost_cents": e["estimated_cost_cents"],
        "notes": e["notes"],
        "status": e["status"],
        "supersedes_estimate_id": e["supersedes_estimate_id"],
        "submitted_by_user_id": e["submitted_by_user_id"],
        "decided_by_user_id": e["decided_by_user_id"],
        "routing_tier": e["routing_tier"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_charge(c):
    return {
        "id": c["id"],
        "work_order_id": c["work_order_id"],
        "cost_type": c["cost_type"],
        "base_amount_cents": c["base_amount_cents"],
        "charge_date": c["charge_date"],
        "accounting_period_id": c["accounting_period_id"],
        "kind": c["kind"],
        "reverses_charge_id": c["reverses_charge_id"],
        "overhead_rate_pct": c["overhead_rate_pct"],
        "overhead_amount_cents": c["overhead_amount_cents"],
        "total_cents": c["total_cents"],
        "status": c["status"],
        "posted_by_user_id": c["posted_by_user_id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_ciac(a):
    return {
        "id": a["id"],
        "work_order_id": a["work_order_id"],
        "pledged_cents": a["pledged_cents"],
        "pledge_expiry_at": a["pledge_expiry_at"],
        "status": a["status"],
        "received_cents": a["received_cents"],
        "applied_cents": a["applied_cents"],
        "forfeited_cents": a["forfeited_cents"],
        "refunded_cents": a["refunded_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_unit(u):
    return {
        "id": u["id"],
        "work_order_id": u["work_order_id"],
        "unit_catalog_id": u["unit_catalog_id"],
        "quantity": u["quantity"],
        "line_no": u["line_no"],
        "allocated_cost_cents": u["allocated_cost_cents"],
        "in_service_period_id": u["in_service_period_id"],
        "retirement_period_id": u["retirement_period_id"],
        "accumulated_depreciation_cents": unit_accumulated_depreciation_cents(u["id"]),
        "retirement_nbv_cents": u["retirement_nbv_cents"],
        "status": u["status"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def serialize_reg_asset(a):
    return {
        "id": a["id"],
        "description": a["description"],
        "source_work_order_id": a["source_work_order_id"],
        "original_cents": a["original_cents"],
        "amortization_months": a["amortization_months"],
        "remaining_cents": asset_remaining_cents(a),
        "status": a["status"],
        "proposed_by_user_id": a["proposed_by_user_id"],
        "approved_by_user_id": a["approved_by_user_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_afudc_entry(e):
    """Ledger entries: only id + created_at (no updated_at / version, PRD 2.4)."""
    return {
        "id": e["id"],
        "work_order_id": e["work_order_id"],
        "accounting_period_id": e["accounting_period_id"],
        "method": e["method"],
        "base_cents": e["base_cents"],
        "rate_pct_applied": e["rate_pct_applied"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
        "created_at": e["created_at"],
    }


def serialize_depreciation_entry(e):
    return {
        "id": e["id"],
        "fixed_asset_unit_id": e["fixed_asset_unit_id"],
        "accounting_period_id": e["accounting_period_id"],
        "amount_cents": e["amount_cents"],
        "ciac_contra_credit_cents": e["ciac_contra_credit_cents"],
        "status": e["status"],
        "created_at": e["created_at"],
    }


def serialize_amortization_entry(e):
    return {
        "id": e["id"],
        "regulatory_asset_id": e["regulatory_asset_id"],
        "accounting_period_id": e["accounting_period_id"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
        "created_at": e["created_at"],
    }
