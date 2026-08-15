"""Underpayment case ledger computations (PRD §3.7)."""

import db as _db


def compute_case_ledger(case):
    """recovered_to_date_cents = sum of recovered_amount_cents over the case's appeals
    with outcome IN {PAID_IN_FULL, PARTIAL_PAYMENT}, MINUS paid amounts of REVERSED
    APPEAL_RECOVERY remittances linked to those appeals.
    current_outstanding_cents = original - recovered - write_off."""
    recovered = 0
    for a in _db.store.appeals.values():
        if a["case_id"] != case["id"]:
            continue
        if a["outcome"] not in {"PAID_IN_FULL", "PARTIAL_PAYMENT"}:
            continue
        recovered += a.get("recovered_amount_cents", 0)
        for r in _db.store.remittances.values():
            if r.get("appeal_id") == a["id"] and r["source"] == "APPEAL_RECOVERY" and r["status"] == "REVERSED":
                recovered -= r["paid_amount_cents"]
    write_off = case.get("write_off_amount_cents", 0)
    outstanding = case["original_variance_cents"] - recovered - write_off
    return {
        "recovered_to_date_cents": recovered,
        "write_off_amount_cents": write_off,
        "current_outstanding_cents": outstanding,
    }
