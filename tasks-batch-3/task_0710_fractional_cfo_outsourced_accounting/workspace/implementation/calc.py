"""Reconciliations and calculations (PRD §2.5, §3.4, §3.6, §3.7, §3.8, §3.5)."""
from store import store
from helpers import touch, round_half_up

# Tier table (PRD §3.8): base_cents, included_txns, overage_rate_milli
TIER_TABLE = {
    "ESSENTIALS": {"base_cents": 150000, "included_txns": 200, "overage_rate_milli": 750},
    "GROWTH": {"base_cents": 300000, "included_txns": 500, "overage_rate_milli": 600},
    "CFO": {"base_cents": 600000, "included_txns": 1200, "overage_rate_milli": 450},
}


# ---------------------------------------------------------------------------
# Client reconciliations (§2.5)
# ---------------------------------------------------------------------------
def reconcile_catchup_active(client):
    """catchup_active is true iff client owns a CatchupProject in SCOPED/IN_PROGRESS."""
    active = any(
        p["client_id"] == client["id"] and p["status"] in ("SCOPED", "IN_PROGRESS")
        for p in store.catchup_projects.values()
    )
    if client["catchup_active"] != active:
        client["catchup_active"] = active
        touch(client)


def reconcile_open_close_count(client):
    """open_close_count = number of MonthlyClose rows for client not FINALIZED."""
    count = sum(
        1 for c in store.monthly_closes.values()
        if c["client_id"] == client["id"] and c["status"] != "FINALIZED"
    )
    if client["open_close_count"] != count:
        client["open_close_count"] = count
        touch(client)


# ---------------------------------------------------------------------------
# MonthlyClose completion (§3.4)
# ---------------------------------------------------------------------------
def recompute_close_completion(close):
    tasks = [t for t in store.close_tasks.values()
             if t["monthly_close_id"] == close["id"]]
    total_weight = sum(t["weight"] for t in tasks)
    if total_weight == 0:
        completion = 0.0
        provisional = 0.0
    else:
        final_done = sum(t["weight"] for t in tasks if t["status"] in ("DONE", "WAIVED"))
        prov_done = sum(t["weight"] for t in tasks
                        if t["status"] in ("DONE", "WAIVED", "IN_REVIEW"))
        completion = round_half_up(final_done / total_weight * 100, 2)
        provisional = round_half_up(prov_done / total_weight * 100, 2)
    close["completion_pct"] = completion
    close["provisional_completion_pct"] = provisional
    return completion, provisional


# ---------------------------------------------------------------------------
# Cash-flow projection (§3.7)
# ---------------------------------------------------------------------------
def recompute_forecast(forecast):
    lines = [ln for ln in store.forecast_lines.values()
             if ln["forecast_id"] == forecast["id"]]
    ordered = sorted(lines, key=lambda ln: (ln["effective_date"], ln["_seq"]))
    balance = forecast["opening_balance_cents"]
    min_balance = forecast["opening_balance_cents"]
    for ln in ordered:
        if ln["direction"] == "INFLOW":
            balance += ln["amount_cents"]
        else:
            balance -= ln["amount_cents"]
        if balance < min_balance:
            min_balance = balance
    forecast["ending_balance_cents"] = balance
    forecast["min_projected_balance_cents"] = min_balance


# ---------------------------------------------------------------------------
# Payroll cost allocation (§3.6)
# ---------------------------------------------------------------------------
def allocate_payroll(run):
    allocs = [a for a in store.payroll_allocations.values()
              if a["payroll_run_id"] == run["id"]]
    total = run["total_employer_cost_cents"]
    sum_gross = sum(a["dept_gross_cents"] for a in allocs)
    raw = {}
    for a in allocs:
        raw[a["id"]] = round_half_up(total * a["dept_gross_cents"] / sum_gross, 0)
    assigned = sum(raw.values())
    remainder = total - assigned
    # recipient: largest dept_gross_cents, tie-break earliest created_at (then _seq)
    recipient = sorted(
        allocs,
        key=lambda a: (-a["dept_gross_cents"], a["created_at"], a["_seq"]),
    )[0]
    raw[recipient["id"]] += remainder
    for a in allocs:
        a["allocated_cents"] = raw[a["id"]]
        touch(a)


def zero_payroll_allocations(run):
    for a in store.payroll_allocations.values():
        if a["payroll_run_id"] == run["id"]:
            a["allocated_cents"] = 0
            touch(a)


# ---------------------------------------------------------------------------
# Retainer invoice amount (§3.8)
# ---------------------------------------------------------------------------
def compute_retainer(client, close):
    tier = client["retainer_tier"]
    t = TIER_TABLE[tier]
    base_cents = t["base_cents"]
    txns = close["txn_count"]
    overage_units = max(0, txns - t["included_txns"])
    overage_cents = round_half_up(overage_units * t["overage_rate_milli"] / 10, 0)
    if client["catchup_active"]:
        surcharge_cents = round_half_up(base_cents * 0.20, 0)
    else:
        surcharge_cents = 0
    total_cents = base_cents + overage_cents + surcharge_cents
    return base_cents, overage_cents, surcharge_cents, total_cents


# ---------------------------------------------------------------------------
# AR summary / DSO (§3.5)
# ---------------------------------------------------------------------------
def ar_summary(client, credit_sales_cents, clock_dt):
    from store import parse_iso
    invoices = [inv for inv in store.ar_invoices.values()
                if inv["client_id"] == client["id"]]
    open_disputed = [inv for inv in invoices if inv["status"] in ("OPEN", "DISPUTED")]
    gross_outstanding = sum(inv["amount_cents"] - inv["paid_amount_cents"]
                            for inv in open_disputed)
    net_outstanding = sum(inv["amount_cents"] - inv["paid_amount_cents"]
                          for inv in open_disputed if inv["status"] == "OPEN")
    if credit_sales_cents == 0:
        dso_gross = 0.0
        dso_net = 0.0
    else:
        dso_gross = round_half_up(gross_outstanding / credit_sales_cents * 30, 2)
        dso_net = round_half_up(net_outstanding / credit_sales_cents * 30, 2)

    # aging buckets by days past due_date vs logical clock
    bucket_current = 0
    bucket_1_30 = 0
    bucket_31_60 = 0
    bucket_61_plus = 0
    for inv in open_disputed:
        outstanding = inv["amount_cents"] - inv["paid_amount_cents"]
        due = parse_iso(inv["due_date"])
        days_past = (clock_dt - due).days
        if days_past <= 0:
            bucket_current += outstanding
        elif days_past <= 30:
            bucket_1_30 += outstanding
        elif days_past <= 60:
            bucket_31_60 += outstanding
        else:
            bucket_61_plus += outstanding

    return {
        "gross_outstanding_cents": gross_outstanding,
        "net_outstanding_cents": net_outstanding,
        "dso_gross": dso_gross,
        "dso_net": dso_net,
        "bucket_current_cents": bucket_current,
        "bucket_1_30_cents": bucket_1_30,
        "bucket_31_60_cents": bucket_31_60,
        "bucket_61_plus_cents": bucket_61_plus,
    }
