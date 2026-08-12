"""Domain services: entity storage, serializers, calendar generation,
proration, totals reconciliation, state cascades, and clock transitions."""

from calendar import monthrange
from datetime import timedelta

import db
from db import store
from errors import err_not_found
from util import fmt_dt, fmt_ts, new_id

FREQ_MONTHS = {"MONTHLY": 1, "QUARTERLY": 3, "SEMIANNUAL": 6, "ANNUAL": 12}
STANDARD_VOLUNTEER_RATE_CENTS = 3150
DE_MINIMIS_INDIRECT_PCT = 10
AUDITOR_MAX_CONCURRENT_ENGAGEMENTS = 2

BUDGET_CATEGORIES = (
    "PERSONNEL", "FRINGE", "TRAVEL", "EQUIPMENT",
    "SUPPLIES", "CONTRACTUAL", "INDIRECT", "OTHER",
)


# ---------------------------------------------------------------------------
# stamping
# ---------------------------------------------------------------------------

def stamp(e):
    ts = fmt_ts(db.now())
    e["id"] = new_id()
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_order"] = db.next_order()
    return e


def touch(e):
    e["updated_at"] = fmt_ts(db.now())
    e["version"] += 1


# ---------------------------------------------------------------------------
# lookups (path-id existence: ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def _lookup(table, rid, label):
    e = store[table].get(rid)
    if e is None:
        raise err_not_found("%s not found: %s" % (label, rid))
    return e


def get_funder(x):
    return _lookup("funders", x, "Funder")


def get_grant(x):
    return _lookup("grants", x, "Grant")


def get_line(x):
    return _lookup("budget_lines", x, "BudgetLine")


def get_fund(x):
    return _lookup("funds", x, "Fund")


def get_expense(x):
    return _lookup("expenses", x, "Expense")


def get_allocation(x):
    return _lookup("allocations", x, "ExpenseAllocation")


def get_report(x):
    return _lookup("reports", x, "Report")


def get_match(x):
    return _lookup("match_contributions", x, "MatchContribution")


def get_mod(x):
    return _lookup("modification_requests", x, "ModificationRequest")


def get_engagement(x):
    return _lookup("audit_engagements", x, "AuditEngagement")


def get_finding(x):
    return _lookup("audit_findings", x, "AuditFinding")


def get_renewal(x):
    return _lookup("renewal_applications", x, "RenewalApplication")


def _children(table, field, pid):
    return sorted(
        (e for e in store[table].values() if e.get(field) == pid),
        key=lambda e: e["_order"],
    )


def grant_lines(gid):
    return _children("budget_lines", "grant_id", gid)


def grant_funds(gid):
    return _children("funds", "grant_id", gid)


def grant_reports(gid):
    return sorted(
        (e for e in store["reports"].values() if e["grant_id"] == gid),
        key=lambda e: e["period_index"],
    )


def grant_expenses(gid):
    return _children("expenses", "grant_id", gid)


def grant_matches(gid):
    return _children("match_contributions", "grant_id", gid)


def grant_mods(gid):
    return _children("modification_requests", "grant_id", gid)


def grant_engagements(gid):
    return _children("audit_engagements", "grant_id", gid)


def grant_renewals(gid):
    return _children("renewal_applications", "grant_id", gid)


def expense_allocations(eid):
    return _children("allocations", "expense_id", eid)


def report_ves(rid):
    return _children("variance_explanations", "report_id", rid)


def engagement_findings(eid):
    return _children("audit_findings", "engagement_id", eid)


def active_allocations(gid):
    """(expense, allocation) pairs for ACTIVE allocations on the grant."""
    out = []
    for exp in grant_expenses(gid):
        for a in expense_allocations(exp["id"]):
            if a["status"] == "ACTIVE":
                out.append((exp, a))
    return out


# ---------------------------------------------------------------------------
# serializers (public field sets; datetimes formatted here)
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_funder(f):
    d = _common(f)
    d.update({
        "name": f["name"],
        "funder_type": f["funder_type"],
        "contact_email": f["contact_email"],
        "requires_match": f["requires_match"],
    })
    return d


def ser_grant(g):
    d = _common(g)
    d.update({
        "funder_id": g["funder_id"],
        "award_number": g["award_number"],
        "title": g["title"],
        "award_amount_cents": g["award_amount_cents"],
        "start_date": fmt_dt(g["start_date"]),
        "end_date": fmt_dt(g["end_date"]),
        "original_end_date": fmt_dt(g["original_end_date"]),
        "reporting_frequency": g["reporting_frequency"],
        "interim_report_due_days": g["interim_report_due_days"],
        "final_report_due_days": g["final_report_due_days"],
        "variance_threshold_pct": g["variance_threshold_pct"],
        "indirect_rate_pct": g["indirect_rate_pct"],
        "indirect_cap_cents": g["indirect_cap_cents"],
        "renewal_window_days": g["renewal_window_days"],
        "required_match_cents": g["required_match_cents"],
        "status": g["status"],
        "total_expended_cents": g["total_expended_cents"],
    })
    return d


def ser_line(l):
    d = _common(l)
    d.update({
        "grant_id": l["grant_id"],
        "category": l["category"],
        "budgeted_cents": l["budgeted_cents"],
        "adjusted_cents": l["adjusted_cents"],
        "expended_cents": l["expended_cents"],
        "period_budgets_cents": list(l["period_budgets_cents"]),
    })
    return d


def ser_fund(f):
    d = _common(f)
    d.update({
        "grant_id": f["grant_id"],
        "fund_type": f["fund_type"],
        "purpose_restriction": f["purpose_restriction"],
        "allowed_categories": list(f["allowed_categories"]),
        "allocated_cents": f["allocated_cents"],
        "expended_cents": f["expended_cents"],
        "remaining_cents": f["allocated_cents"] - f["expended_cents"],
    })
    return d


def ser_expense(e):
    d = _common(e)
    d.update({
        "grant_id": e["grant_id"],
        "expense_date": fmt_dt(e["expense_date"]),
        "vendor": e["vendor"],
        "description": e["description"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
        "unallocated_cents": e["unallocated_cents"],
        "created_by_user_id": e["created_by_user_id"],
        "posted_by_user_id": e["posted_by_user_id"],
    })
    return d


def ser_allocation(a):
    d = _common(a)
    d.update({
        "expense_id": a["expense_id"],
        "budget_line_id": a["budget_line_id"],
        "fund_id": a["fund_id"],
        "amount_cents": a["amount_cents"],
        "status": a["status"],
        "created_by_user_id": a["created_by_user_id"],
    })
    return d


def ser_report(r):
    d = _common(r)
    d.update({
        "grant_id": r["grant_id"],
        "period_index": r["period_index"],
        "period_type": r["period_type"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "due_date": fmt_dt(r["due_date"]),
        "status": r["status"],
        "narrative_draft": r["narrative_draft"],
        "outcome_entries": list(r["outcome_entries"]),
        "frozen": r["frozen"],
        "revision_count": r["revision_count"],
        "submitted_at": fmt_dt(r["submitted_at"]) if r["submitted_at"] else None,
        "submitted_late": r["submitted_late"],
        "prepared_by_user_id": r["prepared_by_user_id"],
        "returned_reason": r["returned_reason"],
    })
    return d


def ser_ve(v):
    d = _common(v)
    d.update({
        "report_id": v["report_id"],
        "budget_line_id": v["budget_line_id"],
        "explanation_text": v["explanation_text"],
        "period_variance_pct_snapshot": v["period_variance_pct_snapshot"],
        "status": v["status"],
    })
    return d


def ser_match(m):
    d = _common(m)
    d.update({
        "grant_id": m["grant_id"],
        "source_name": m["source_name"],
        "contribution_type": m["contribution_type"],
        "valuation_basis": m["valuation_basis"],
        "documented_value_cents": m["documented_value_cents"],
        "volunteer_hours": m["volunteer_hours"],
        "recognized_value_cents": m["recognized_value_cents"],
        "status": m["status"],
        "documented_by_user_id": m["documented_by_user_id"],
        "verified_by_user_id": m["verified_by_user_id"],
    })
    return d


def ser_mod(m):
    d = _common(m)
    d.update({
        "grant_id": m["grant_id"],
        "request_type": m["request_type"],
        "justification": m["justification"],
        "requested_end_date": fmt_dt(m["requested_end_date"]) if m["requested_end_date"] else None,
        "line_deltas": [dict(x) for x in m["line_deltas"]],
        "status": m["status"],
        "created_by_user_id": m["created_by_user_id"],
        "submitted_by_user_id": m["submitted_by_user_id"],
        "decided_by_funder_id": m["decided_by_funder_id"],
    })
    return d


def ser_engagement(e):
    d = _common(e)
    d.update({
        "grant_id": e["grant_id"],
        "engagement_type": e["engagement_type"],
        "auditor_org": e["auditor_org"],
        "scheduled_start": fmt_dt(e["scheduled_start"]),
        "scheduled_end": fmt_dt(e["scheduled_end"]),
        "status": e["status"],
    })
    return d


def ser_finding(f):
    d = _common(f)
    d.update({
        "engagement_id": f["engagement_id"],
        "severity": f["severity"],
        "description": f["description"],
        "status": f["status"],
        "response_text": f["response_text"],
    })
    return d


def ser_renewal(r):
    d = _common(r)
    d.update({
        "grant_id": r["grant_id"],
        "window_open": fmt_dt(r["window_open"]),
        "window_close": fmt_dt(r["window_close"]),
        "status": r["status"],
        "submitted_at": fmt_dt(r["submitted_at"]) if r["submitted_at"] else None,
    })
    return d


# ---------------------------------------------------------------------------
# reporting calendar + proration
# ---------------------------------------------------------------------------

def add_months(d, m):
    y = d.year + (d.month - 1 + m) // 12
    mo = (d.month - 1 + m) % 12 + 1
    day = min(d.day, monthrange(y, mo)[1])
    return d.replace(year=y, month=mo, day=day)


def tile_periods(anchor, end, months):
    """Tile [anchor, end] with month-sized periods; last clamps to end."""
    periods = []
    k = 0
    while True:
        ps = add_months(anchor, k * months)
        if ps > end:
            break
        pe = add_months(anchor, (k + 1) * months) - timedelta(days=1)
        if pe > end:
            pe = end
        periods.append((ps, pe))
        k += 1
    return periods


def create_report(grant, idx, ptype, ps, pe):
    due_days = (
        grant["final_report_due_days"] if ptype == "FINAL"
        else grant["interim_report_due_days"]
    )
    rep = stamp({
        "grant_id": grant["id"],
        "period_index": idx,
        "period_type": ptype,
        "period_start": ps,
        "period_end": pe,
        "due_date": pe + timedelta(days=due_days),
        "status": "SCHEDULED",
        "narrative_draft": "",
        "outcome_entries": [],
        "frozen": False,
        "revision_count": 0,
        "submitted_at": None,
        "submitted_late": False,
        "prepared_by_user_id": None,
        "returned_reason": None,
    })
    store["reports"][rep["id"]] = rep
    return rep


def generate_calendar(grant):
    months = FREQ_MONTHS[grant["reporting_frequency"]]
    periods = tile_periods(grant["start_date"], grant["end_date"], months)
    n = len(periods)
    for i, (ps, pe) in enumerate(periods, start=1):
        create_report(grant, i, "FINAL" if i == n else "INTERIM", ps, pe)
    return n


def recompute_proration(line, n):
    """Waterfall: floor per period, residual to the FINAL period (pinned order)."""
    adj = line["adjusted_cents"]
    if n <= 0:
        line["period_budgets_cents"] = []
        return
    base = adj // n  # integer cents, round DOWN per period
    rem = adj - base * n
    line["period_budgets_cents"] = [base] * (n - 1) + [base + rem]


# ---------------------------------------------------------------------------
# totals reconciliation
# ---------------------------------------------------------------------------

def recompute_expense_unallocated(exp):
    used = sum(
        a["amount_cents"]
        for a in expense_allocations(exp["id"])
        if a["status"] == "ACTIVE"
    )
    exp["unallocated_cents"] = exp["amount_cents"] - used


def recompute_grant_total(grant):
    grant["total_expended_cents"] = sum(
        a["amount_cents"] for _, a in active_allocations(grant["id"])
    )


# ---------------------------------------------------------------------------
# period membership / actuals
# ---------------------------------------------------------------------------

def period_contains(rep, dt):
    """Period membership: period_start <= dt <= period_end (inclusive date)."""
    return rep["period_start"] <= dt < rep["period_end"] + timedelta(days=1)


def period_actual(line, rep):
    total = 0
    for exp, a in active_allocations(rep["grant_id"]):
        if a["budget_line_id"] == line["id"] and period_contains(rep, exp["expense_date"]):
            total += a["amount_cents"]
    return total


def cumulative_actual(line, rep):
    cutoff = rep["period_end"] + timedelta(days=1)
    total = 0
    for exp, a in active_allocations(rep["grant_id"]):
        if a["budget_line_id"] == line["id"] and exp["expense_date"] < cutoff:
            total += a["amount_cents"]
    return total


def period_budget(line, period_index):
    pbs = line["period_budgets_cents"]
    if 1 <= period_index <= len(pbs):
        return pbs[period_index - 1]
    return 0


def cumulative_budget(line, period_index):
    return sum(line["period_budgets_cents"][:period_index])


def period_total(grant_id, rep):
    total = 0
    for exp, a in active_allocations(grant_id):
        if period_contains(rep, exp["expense_date"]):
            total += a["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# grant state guards
# ---------------------------------------------------------------------------

def require_grant_active(grant):
    """Guard for operations that need grant ACTIVE (PRD named pair)."""
    if grant["status"] == "SUSPENDED":
        from errors import err_grant_suspended
        raise err_grant_suspended()
    if grant["status"] != "ACTIVE":
        from errors import err_grant_not_active
        raise err_grant_not_active()


# ---------------------------------------------------------------------------
# suspension / reactivation cascades
# ---------------------------------------------------------------------------

def suspend_grant(grant):
    from errors import err_invalid_state  # noqa: F401  (kept for parity)
    grant["status"] = "SUSPENDED"
    touch(grant)
    for rep in grant_reports(grant["id"]):
        if rep["status"] in ("DRAFT", "RETURNED"):
            rep["frozen"] = True
            touch(rep)
            for ve in report_ves(rep["id"]):
                if ve["status"] == "DRAFTED":
                    ve["status"] = "LOCKED"
                    touch(ve)


def maybe_reactivate_grant(grant):
    """Reactivate when no OPEN/RESPONSE_SUBMITTED MATERIAL_WEAKNESS remains."""
    for eng in grant_engagements(grant["id"]):
        for f in engagement_findings(eng["id"]):
            if f["severity"] == "MATERIAL_WEAKNESS" and f["status"] in ("OPEN", "RESPONSE_SUBMITTED"):
                return
    if grant["status"] != "SUSPENDED":
        return
    grant["status"] = "ACTIVE"
    touch(grant)
    for rep in grant_reports(grant["id"]):
        if rep["frozen"]:
            rep["frozen"] = False
            touch(rep)
        for ve in report_ves(rep["id"]):
            if ve["status"] == "LOCKED":
                ve["status"] = "DRAFTED"
                touch(ve)


# ---------------------------------------------------------------------------
# no-cost-extension calendar regeneration
# ---------------------------------------------------------------------------

def apply_nce_calendar(grant, old_end, new_end):
    """Demote the still-SCHEDULED FINAL to INTERIM, then append new periods
    tiling [old_end + 1 day, new_end] with the last marked FINAL."""
    reports = grant_reports(grant["id"])
    for rep in reversed(reports):
        if rep["period_type"] == "FINAL" and rep["status"] == "SCHEDULED":
            rep["period_type"] = "INTERIM"
            rep["due_date"] = rep["period_end"] + timedelta(days=grant["interim_report_due_days"])
            touch(rep)
            break
    months = FREQ_MONTHS[grant["reporting_frequency"]]
    anchor = old_end + timedelta(days=1)
    periods = tile_periods(anchor, new_end, months)
    next_idx = (max(r["period_index"] for r in reports) + 1) if reports else 1
    for i, (ps, pe) in enumerate(periods):
        ptype = "FINAL" if i == len(periods) - 1 else "INTERIM"
        create_report(grant, next_idx + i, ptype, ps, pe)


# ---------------------------------------------------------------------------
# clock transitions
# ---------------------------------------------------------------------------

def fire_clock_transitions():
    now = db.now()
    for r in list(store["renewal_applications"].values()):
        if r["status"] == "NOT_OPEN" and now >= r["window_open"]:
            r["status"] = "ELIGIBLE"
            touch(r)
        if r["status"] == "ELIGIBLE" and now > r["window_close"]:
            r["status"] = "LAPSED"
            touch(r)
