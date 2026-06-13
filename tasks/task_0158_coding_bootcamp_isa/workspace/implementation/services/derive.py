"""Derived-field reconciliation.

The ISA ledger (amount_paid_cents / payments_made_count / remaining_cap_cents) is
kept consistent with the Payment rows at all times (PRD §2.5, §2.6). We recompute
it from the SETTLED payment ledger whenever payments change, storing canonical
values under private keys on the contract so calculations read a single source.
"""
from db import db


def recompute_isa_ledger(contract):
    """Sum SETTLED, non-REVERSED payments into the contract ledger fields."""
    settled = [
        p for p in db.payments.values()
        if p["isa_contract_id"] == contract["id"]
        and p["collection_status"] == "SETTLED"
        and p["refund_status"] == "NONE"
    ]
    amount_paid = sum(p["amount_cents"] for p in settled)
    contract["_amount_paid_cents"] = amount_paid
    contract["_payments_made_count"] = len(settled)
    contract["_remaining_cap_cents"] = contract["cap_cents"] - amount_paid


def enrollment_attendance(enrollment_id):
    """(attendance_pct, progress_pct) from AttendanceRecord rows (PRD §3.4)."""
    records = [r for r in db.attendance_records.values() if r["enrollment_id"] == enrollment_id]
    if not records:
        return 0, 0
    present = sum(1 for r in records if r["present"])
    total = len(records)
    attendance_pct = 100 * present / total
    latest = max(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    progress_pct = latest["cumulative_progress_pct"]
    return attendance_pct, progress_pct


def seats_committed(cohort_id):
    return sum(
        1 for e in db.enrollments.values()
        if e["cohort_id"] == cohort_id and e["status"] in ("ENROLLED", "ACTIVE", "GRADUATED")
    )


def latest_income_report(contract_id):
    """Most recent IncomeReport by (period_start DESC, created_at DESC)."""
    reports = [r for r in db.income_reports.values() if r["isa_contract_id"] == contract_id]
    if not reports:
        return None
    return max(reports, key=lambda r: (r["_period_start_key"], r["created_at"], r.get("_seq", 0)))
