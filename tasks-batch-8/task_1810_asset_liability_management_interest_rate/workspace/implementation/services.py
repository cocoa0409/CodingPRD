"""Cross-entity services: record lifecycle, book aggregates, cascade side
effects, breach creation, ALCO report upsert/recompute, and the clock-driven
escalation sweep (PRD 3.5).
"""

import uuid

import store
from calc import PRESET_CODES
from timeutil import add_days, clock, parse_instant


# ---------------------------------------------------------------------------
# Record lifecycle (PRD 2.5 common resource properties)
# ---------------------------------------------------------------------------

def stamp_new(record):
    """System fields on creation: id (UUID, no prefix), created_at/updated_at
    from the logical clock, version starting at 1."""
    record["id"] = str(uuid.uuid4())
    record["_seq"] = store.next_seq()
    record["_created_dt"] = clock.now
    record["created_at"] = clock.now_string()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    return record


def stamp_event(record):
    """HedgeEffectivenessTest: append-only, id + created_at only (PRD 2.5)."""
    record["id"] = str(uuid.uuid4())
    record["_seq"] = store.next_seq()
    record["_created_dt"] = clock.now
    record["created_at"] = clock.now_string()
    return record


def touch(record):
    """Every mutation refreshes updated_at and increments version (PRD 2.8)."""
    record["version"] += 1
    record["updated_at"] = clock.now_string()


# ---------------------------------------------------------------------------
# Book aggregates (PRD 2.8)
# ---------------------------------------------------------------------------

def positions_of_book(book_id):
    return [p for p in store.positions.values() if p["book_id"] == book_id]


def active_positions(book_id):
    return [p for p in positions_of_book(book_id) if p["status"] == "ACTIVE"]


def recompute_book_totals(book):
    """total_assets/total_liabilities over ACTIVE positions. Callers bump the
    book version themselves where PRD 2.8 requires it."""
    active = active_positions(book["id"])
    book["total_assets_cents"] = sum(
        p["balance_cents"] for p in active if p["category"] in ("LOAN", "SECURITY")
    )
    book["total_liabilities_cents"] = sum(
        p["balance_cents"] for p in active if p["category"] in ("DEPOSIT", "BORROWING")
    )


def recompute_hedged_notional(book):
    """hedged_notional_cents over DESIGNATED/ACTIVE hedges of this book.
    Hedge lifecycle events recompute this aggregate WITHOUT advancing the
    book version (PRD 2.8 lists the version-advancing mutations and hedge
    events are not among them)."""
    book["hedged_notional_cents"] = sum(
        h["notional_cents"]
        for h in store.hedges.values()
        if h["book_id"] == book["id"] and h["status"] in ("DESIGNATED", "ACTIVE")
    )


# ---------------------------------------------------------------------------
# LimitBreach creation and the hedge coverage floor check
# ---------------------------------------------------------------------------

def make_breach(book_id, run_id, limit_id, metric, observed_delta_pct, threshold_pct):
    breach = {
        "book_id": book_id,
        "run_id": run_id,
        "limit_id": limit_id,
        "metric": metric,
        "observed_delta_pct": observed_delta_pct,
        "threshold_pct": threshold_pct,
        "period_month": clock.period_month(),
        "status": "OPEN",
        "remediation_note": None,
        "due_date": None,
        "resolution_note": None,
    }
    stamp_new(breach)
    store.breaches[breach["id"]] = breach
    # A breach creation recomputes the period report and reverts a SUBMITTED
    # report to DRAFT (PRD 3.8), creating the report in DRAFT when absent.
    upsert_report_on_event(book_id, breach["period_month"])
    return breach


def hedge_coverage_floor_check(book):
    """Runs only after a DECREASE of hedged_notional_cents (dedesignate,
    terminate, FAIL-driven dedesignation); increases never trigger it."""
    if book["hedged_notional_cents"] < book["min_hedged_notional_cents"]:
        make_breach(book["id"], None, None, "HEDGE_COVERAGE", None, None)


# ---------------------------------------------------------------------------
# AlcoReport aggregates and volatility (PRD 3.8)
# ---------------------------------------------------------------------------

def find_open_report(book_id, period_month):
    """The non-terminal (DRAFT or SUBMITTED) report for the pair, if any."""
    for report in store.reports.values():
        if (
            report["book_id"] == book_id
            and report["period_month"] == period_month
            and report["status"] in ("DRAFT", "SUBMITTED")
        ):
            return report
    return None


def recompute_report(report):
    """alco_report_aggregates: run_count, worst deltas, open_breach_count,
    regulatory_coverage_complete over the book+period."""
    book_id = report["book_id"]
    period = report["period_month"]
    published = [
        r for r in store.runs.values()
        if r["book_id"] == book_id and r["period_month"] == period
        and r["status"] == "PUBLISHED"
    ]
    report["run_count"] = len(published)
    report["worst_nii_delta_pct"] = (
        min(r["nii_delta_pct"] for r in published) if published else None
    )
    report["worst_eve_delta_pct"] = (
        min(r["eve_delta_pct"] for r in published) if published else None
    )
    report["open_breach_count"] = sum(
        1 for b in store.breaches.values()
        if b["book_id"] == book_id and b["period_month"] == period
        and b["status"] != "CLOSED"
    )
    covered = set()
    for r in published:
        scenario = store.scenarios.get(r["scenario_id"])
        if scenario is not None and scenario["kind"] == "REGULATORY_PRESET":
            covered.add(scenario["preset_code"])
    report["regulatory_coverage_complete"] = all(code in covered for code in PRESET_CODES)


def new_report(book_id, period_month):
    report = {
        "book_id": book_id,
        "period_month": period_month,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "acknowledged_by_user_id": None,
    }
    stamp_new(report)
    recompute_report(report)
    store.reports[report["id"]] = report
    return report


def upsert_report_on_event(book_id, period_month):
    """Run publish or breach creation: create the period report in DRAFT when
    absent, recompute aggregates, and auto-revert SUBMITTED -> DRAFT with
    submitted_by_user_id reset."""
    report = find_open_report(book_id, period_month)
    if report is None:
        return new_report(book_id, period_month)
    recompute_report(report)
    if report["status"] == "SUBMITTED":
        report["status"] = "DRAFT"
        report["submitted_by_user_id"] = None
    touch(report)
    return report


def recompute_report_if_exists(book_id, period_month):
    """Breach acknowledge/close recompute open_breach_count but do NOT revert
    a SUBMITTED report (PRD 3.8), and never create a report."""
    report = find_open_report(book_id, period_month)
    if report is not None:
        recompute_report(report)
        touch(report)


# ---------------------------------------------------------------------------
# SimulationRun derivation
# ---------------------------------------------------------------------------

def run_assumption_stale(run):
    """Definitional (PRD 3.2): true whenever any pinned set is no longer
    APPROVED (e.g. superseded after the run was created)."""
    for key in ("prepayment_set_id", "decay_set_id", "beta_set_id"):
        aset = store.assumption_sets.get(run[key])
        if aset is None or aset["status"] != "APPROVED":
            return True
    return False


# ---------------------------------------------------------------------------
# Breach escalation sweep (PRD 3.5), triggered by POST /_clock/set_current_utc
# ---------------------------------------------------------------------------

def escalation_sweep():
    now = clock.now
    for breach in store.breaches.values():
        if breach["status"] == "OPEN":
            # still OPEN once the clock reaches or passes created_at + 5 days
            if now >= add_days(breach["_created_dt"], 5):
                breach["status"] = "ESCALATED"
                touch(breach)
        elif breach["status"] == "REMEDIATION_PLANNED":
            # clock past due_date (and not CLOSED)
            due = parse_instant(breach["due_date"]) if breach["due_date"] else None
            if due is not None and now > due:
                breach["status"] = "ESCALATED"
                touch(breach)
