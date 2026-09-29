"""Derived-field recomputation and cascade helpers (PRD 2.7)."""
from decimal import Decimal

from db import db, ordered, touch
from services.calc import (
    BREACH_THRESHOLD_PCT,
    D,
    HOURS_PER_PERIOD,
    WARN_THRESHOLD_PCT,
    pct2,
    rhu,
)


# --------------------------------------------------------------------------
# tree helpers
# --------------------------------------------------------------------------
def subtree_ids(bu_id):
    """The business unit plus every descendant through parent_business_unit_id."""
    found = {bu_id}
    changed = True
    while changed:
        changed = False
        for bu in db.business_units.values():
            parent = bu.get("parent_business_unit_id")
            if parent in found and bu["id"] not in found:
                found.add(bu["id"])
                changed = True
    return found


# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------
def run_lines(run_id):
    return ordered([l for l in db.allocation_lines.values() if l["allocation_run_id"] == run_id])


def run_invoices(run_id):
    return ordered([i for i in db.chargeback_invoices.values() if i["allocation_run_id"] == run_id])


def run_pools(run_id):
    return ordered([p for p in db.shared_cost_pools.values() if p["allocation_run_id"] == run_id])


def invoice_disputes(invoice_id):
    return ordered([d for d in db.disputes.values() if d["chargeback_invoice_id"] == invoice_id])


def bu_line_total(run_id, bu_id):
    return sum(
        l["allocated_cents"]
        for l in db.allocation_lines.values()
        if l["allocation_run_id"] == run_id and l["business_unit_id"] == bu_id
    )


def invoice_record_ids(invoice):
    """Cost records referenced by the lines of the invoice's business unit."""
    ids = []
    for line in run_lines(invoice["allocation_run_id"]):
        if line["business_unit_id"] != invoice["business_unit_id"]:
            continue
        for rid in line.get("_cost_record_ids", []):
            if rid not in ids:
                ids.append(rid)
    return ids


def resource_tasks(resource_id):
    return ordered([t for t in db.remediation_tasks.values() if t["cloud_resource_id"] == resource_id])


NON_TERMINAL_TASK_STATES = ("PROPOSED", "OWNER_NOTIFIED", "OWNER_SNOOZED", "APPROVED")


def has_open_task(resource_id, exclude_id=None):
    for task in db.remediation_tasks.values():
        if task["cloud_resource_id"] != resource_id:
            continue
        if exclude_id is not None and task["id"] == exclude_id:
            continue
        if task["status"] in NON_TERMINAL_TASK_STATES:
            return True
    return False


# --------------------------------------------------------------------------
# generic apply helper
# --------------------------------------------------------------------------
def _apply(entity, values, bump):
    changed = False
    for key, value in values.items():
        if entity.get(key) != value:
            entity[key] = value
            changed = True
    if changed and bump:
        touch(entity)
    return changed


# --------------------------------------------------------------------------
# BusinessUnit derived ledgers (PRD 3.1)
# --------------------------------------------------------------------------
def bu_values(bu):
    bu_id = bu["id"]
    live = [
        r
        for r in db.cloud_resources.values()
        if r["business_unit_id"] == bu_id and r["lifecycle_state"] != "TERMINATED"
    ]
    direct = [
        c
        for c in db.cost_records.values()
        if c["business_unit_id"] == bu_id and c["allocation_state"] != "REVERSED"
    ]
    showback = 0
    for line in db.allocation_lines.values():
        if line["business_unit_id"] != bu_id:
            continue
        run = db.allocation_runs.get(line["allocation_run_id"])
        if run and run["mode"] == "SHOWBACK" and run["status"] in ("PUBLISHED", "CLOSED"):
            showback += line["allocated_cents"]
    balance = 0
    for invoice in db.chargeback_invoices.values():
        if invoice["business_unit_id"] != bu_id:
            continue
        if invoice["settlement_status"] in ("VOIDED", "WRITTEN_OFF"):
            continue
        balance += invoice["net_due_cents"]
    return {
        "resource_count": len(live),
        "tracked_run_rate_cents": sum(r["monthly_run_rate_cents"] for r in live),
        "direct_spend_cents": sum(c["effective_cost_cents"] for c in direct),
        "showback_total_cents": showback,
        "chargeback_balance_cents": balance,
    }


def bu_sync(bu, bump=True):
    if bu is None:
        return False
    return _apply(bu, bu_values(bu), bump)


def bu_sync_id(bu_id, bump=True):
    return bu_sync(db.business_units.get(bu_id), bump)


def bu_sync_all(bump=True):
    for bu in list(db.business_units.values()):
        bu_sync(bu, bump)


# --------------------------------------------------------------------------
# TaggingPolicy.rejection_count (PRD 3.2)
# --------------------------------------------------------------------------
def policy_sync(policy, bump=True):
    if policy is None:
        return False
    count = sum(
        1
        for r in db.provisioning_requests.values()
        if r["tagging_policy_id"] == policy["id"] and r["status"] == "TAG_REJECTED"
    )
    return _apply(policy, {"rejection_count": count}, bump)


# --------------------------------------------------------------------------
# SharedCostPool aggregates (PRD 3.5)
# --------------------------------------------------------------------------
def pool_records(pool_id):
    return ordered([c for c in db.cost_records.values() if c["shared_cost_pool_id"] == pool_id])


def pool_sync(pool, bump=True):
    if pool is None:
        return False
    records = pool_records(pool["id"])
    return _apply(
        pool,
        {
            "pooled_cost_cents": sum(r["effective_cost_cents"] for r in records),
            "absorbed_record_count": len(records),
        },
        bump,
    )


# --------------------------------------------------------------------------
# ChargebackInvoice settlement ledger (PRD 3.6)
# --------------------------------------------------------------------------
def invoice_values(invoice):
    credited = sum(
        d["granted_credit_cents"]
        for d in db.disputes.values()
        if d["chargeback_invoice_id"] == invoice["id"] and d["status"] == "RESOLVED_ADJUSTED"
    )
    paid = sum(invoice.get("_payments", []))
    if invoice["settlement_status"] in ("SETTLED", "WRITTEN_OFF", "VOIDED"):
        net = 0
    else:
        net = invoice["gross_amount_cents"] - credited - paid
    return {
        "credited_amount_cents": credited,
        "paid_amount_cents": paid,
        "net_due_cents": net,
    }


def invoice_sync(invoice, bump=True):
    if invoice is None:
        return False
    return _apply(invoice, invoice_values(invoice), bump)


# --------------------------------------------------------------------------
# Commitment coverage (PRD 3.4)
# --------------------------------------------------------------------------
def commitment_values(commitment):
    capacity = commitment["hourly_commit_cents"] * HOURS_PER_PERIOD
    covered = sum(
        c["list_cost_cents"]
        for c in db.cost_records.values()
        if c["applied_commitment_id"] == commitment["id"] and c["allocation_state"] != "REVERSED"
    )
    waste = max(0, capacity - covered)
    utilization = pct2(D(covered) / D(capacity) * 100) if capacity else 0.00
    in_scope_total = commitment.get("_in_scope_list_total", 0)
    coverage = pct2(D(covered) / D(in_scope_total) * 100) if in_scope_total else 0.00
    return {
        "committed_capacity_cents": capacity,
        "covered_spend_cents": covered,
        "waste_cents": waste,
        "utilization_pct": utilization,
        "coverage_pct": coverage,
    }


def commitment_sync(commitment, bump=True, allow_transition=True):
    """Recompute coverage figures; optionally slide ACTIVE -> UNDER_UTILIZED."""
    if commitment is None:
        return False
    values = commitment_values(commitment)
    if allow_transition and commitment["status"] == "ACTIVE":
        if D(values["utilization_pct"]) < D(commitment["utilization_target_pct"]):
            values["status"] = "UNDER_UTILIZED"
    return _apply(commitment, values, bump)


# --------------------------------------------------------------------------
# Budget evaluation (PRD 3.9)
# --------------------------------------------------------------------------
def budget_actual_spend(budget):
    bu_id = budget["business_unit_id"]
    start = budget["_period_start_dt"]
    end = budget["_period_end_dt"]
    invoiced = 0
    for invoice in db.chargeback_invoices.values():
        if invoice["business_unit_id"] != bu_id:
            continue
        if invoice["settlement_status"] == "VOIDED":
            continue
        run = db.allocation_runs.get(invoice["allocation_run_id"])
        if run is None:
            continue
        if run["_period_start_dt"] >= start and run["_period_end_dt"] <= end:
            invoiced += invoice["gross_amount_cents"] - invoice["credited_amount_cents"]
    uninvoiced = 0
    for record in db.cost_records.values():
        if record["business_unit_id"] != bu_id:
            continue
        if record["allocation_state"] != "UNALLOCATED":
            continue
        if record["_billing_period_start_dt"] >= start and record["_billing_period_end_dt"] <= end:
            uninvoiced += record["effective_cost_cents"]
    return invoiced + uninvoiced


def budget_forecast_accuracy(budget, actual):
    basis = budget["accuracy_basis"]
    if actual == 0:
        return 0.00
    if basis == "PERIOD_END_BASIS":
        ratio = abs(D(budget["forecast_cents"]) - D(actual)) / D(actual)
        return pct2(D(100) - ratio * 100)
    history = budget.get("forecast_history") or []
    if not history:
        return pct2(D(100))
    total = Decimal(0)
    for entry in history:
        total += abs(D(entry) - D(actual)) / D(actual)
    mean = total / D(len(history))
    return pct2(D(100) - mean * 100)


def budget_evaluate(budget, bump=True):
    """Runs calculation forecast_accuracy_and_variance and drives the status."""
    actual = budget_actual_spend(budget)
    amount = budget["amount_cents"]
    variance = actual - amount
    variance_pct = rhu(D(variance) / D(amount) * 100, 2) if amount else Decimal("0.00")
    warning = bool(WARN_THRESHOLD_PCT <= variance_pct < BREACH_THRESHOLD_PCT)
    values = {
        "actual_spend_cents": actual,
        "variance_cents": variance,
        "variance_pct": float(variance_pct),
        "forecast_accuracy_pct": budget_forecast_accuracy(budget, actual),
        "accuracy_basis_applied": budget["accuracy_basis"],
        "warning_flag": warning,
    }
    if budget["status"] in ("ACTIVE", "BREACHED"):
        values["status"] = "BREACHED" if variance_pct >= BREACH_THRESHOLD_PCT else "ACTIVE"
    _apply(budget, values, bump)
    return budget


def budget_cascade(bu_id):
    """Re-evaluate the BU's ACTIVE or BREACHED budgets after an invoice change."""
    for budget in ordered(list(db.budgets.values())):
        if budget["business_unit_id"] != bu_id:
            continue
        if budget["status"] not in ("ACTIVE", "BREACHED"):
            continue
        budget_evaluate(budget, bump=True)


def covering_budget(bu_id, instant, statuses=None):
    """The BU's budget whose half-open period covers the given instant."""
    for budget in ordered(list(db.budgets.values())):
        if budget["business_unit_id"] != bu_id:
            continue
        if statuses is not None and budget["status"] not in statuses:
            continue
        if budget["_period_start_dt"] <= instant < budget["_period_end_dt"]:
            return budget
    return None
