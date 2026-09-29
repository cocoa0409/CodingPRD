"""Cascade discipline, re-aggregation and full ledger recomputation.

PRD §2.10 (cascade discipline), §2.11 (ledger conservation and full recompute).
Every entity touched by a cascade gets its own version increment and its own
updated_at refresh, exactly as if it had been mutated directly.
"""

import clock
import db
from numeric import dec, money, round_half_up


# ---------------------------------------------------------------------------
# Submission booked totals — round-then-sum (PRD §2.7 / §3.4)
# ---------------------------------------------------------------------------
def recompute_submission_totals(sub):
    lines = [t for t in db.transaction_records.values() if t["submission_id"] == sub["id"]]
    lots = [l for l in db.wholesale_lots.values() if l["submission_id"] == sub["id"]]

    sub["reported_head"] = sum(t["head_count"] for t in lines)
    cwt_total = dec(0)
    for t in lines:
        cwt_total += round_half_up(dec(t["head_count"]) * dec(t["avg_carcass_weight_cwt"]), 2)
    sub["reported_cwt"] = money(cwt_total)

    value_total = dec(0)
    for t in lines:
        value_total += dec(t["line_value_dollars"])
    for l in lots:
        value_total += dec(l["lot_value_dollars"])
    sub["reported_value_dollars"] = money(value_total)

    pounds_total = dec(0)
    for l in lots:
        pounds_total += dec(l["total_pounds"])
    sub["reported_pounds"] = money(pounds_total)
    sub["reported_load_count"] = sum(l["load_count"] for l in lots)


# ---------------------------------------------------------------------------
# Window ledger (PRD §2.11)
# ---------------------------------------------------------------------------
def recompute_window_ledger(window):
    accepted = [
        s
        for s in db.submissions.values()
        if s["reporting_window_id"] == window["id"] and s["status"] == "ACCEPTED"
    ]
    window["accepted_submission_count"] = len(accepted)
    window["total_head_reported"] = sum(int(s["reported_head"] or 0) for s in accepted)
    db.touch(window)


# ---------------------------------------------------------------------------
# Market report staleness (PRD §2.10 data-movement chain)
# ---------------------------------------------------------------------------
def _make_report_stale(report):
    report["aggregation_state"] = "STALE"
    report["disclosure_state"] = "UNREVIEWED"
    report["suppression_reason"] = None
    if report["publication_state"] == "PUBLISHED":
        report["publication_state"] = "WITHDRAWN"
    db.touch(report)


def settle_window_publication(window):
    """A window with no remaining PUBLISHED report falls back PUBLISHED -> LOCKED."""
    if window is None or window["status"] != "PUBLISHED":
        return
    still_published = any(
        r["reporting_window_id"] == window["id"] and r["publication_state"] == "PUBLISHED"
        for r in db.market_reports.values()
    )
    if not still_published:
        window["status"] = "LOCKED"
        db.touch(window)


def stale_computed_reports_of_window(window):
    """Force every COMPUTED report of this window to STALE and settle the window."""
    reports = [
        r
        for r in db.market_reports.values()
        if r["reporting_window_id"] == window["id"] and r["aggregation_state"] == "COMPUTED"
    ]
    for report in db.ordered(reports):
        _make_report_stale(report)
    settle_window_publication(window)


def submission_acceptance_changed(window):
    """Any submission entering or leaving ACCEPTED drives the data-movement chain."""
    recompute_window_ledger(window)
    stale_computed_reports_of_window(window)


# ---------------------------------------------------------------------------
# Enforcement chain (PRD §2.10 / §3.8)
# ---------------------------------------------------------------------------
def void_in_flight_submissions(reporting_entity_id):
    """A registration entering SUSPENDED or REVOKED voids DRAFT / SUBMITTED filings."""
    plant_ids = {
        p["id"]
        for p in db.plants.values()
        if p["reporting_entity_id"] == reporting_entity_id
    }
    if not plant_ids:
        return
    targets = [
        s
        for s in db.submissions.values()
        if s["plant_id"] in plant_ids and s["status"] in ("DRAFT", "SUBMITTED")
    ]
    for sub in db.ordered(targets):
        sub["status"] = "VOIDED"
        db.touch(sub)


# ---------------------------------------------------------------------------
# Firm penalty ledger (PRD §2.11)
# ---------------------------------------------------------------------------
def recompute_entity_penalty_ledger(entity):
    rows = [
        a
        for a in db.penalty_assessments.values()
        if a["reporting_entity_id"] == entity["id"]
    ]
    entity["assessed_penalty_cents"] = sum(int(a["assessed_amount_cents"] or 0) for a in rows)
    entity["paid_penalty_cents"] = sum(
        int(a["assessed_amount_cents"] or 0) for a in rows if a["status"] == "PAID"
    )
    entity["waived_penalty_cents"] = sum(
        int(a["assessed_amount_cents"] or 0) for a in rows if a["status"] == "WAIVED"
    )
    entity["outstanding_penalty_cents"] = sum(
        int(a["assessed_amount_cents"] or 0) for a in rows if a["status"] == "ASSESSED"
    )
    entity["delinquency_points"] = sum(
        int(a["points"] or 0) for a in rows if a["status"] in ("ASSESSED", "PAID")
    )
    db.touch(entity)


def stamp(rec, field):
    rec[field] = clock.iso_now()
