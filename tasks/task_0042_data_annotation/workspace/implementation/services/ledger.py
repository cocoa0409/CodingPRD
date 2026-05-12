"""SalaryLedgerEntry helpers."""

from __future__ import annotations

import db
from services.audit import write_audit


_SALARY_KINDS = {"PIECE_RATE", "BONUS", "PENALTY", "ADJUSTMENT_UPHELD",
                 "ADJUSTMENT_REJECTED", "TAX", "WITHHOLD", "RELEASE"}


def add_entry(*, annotator_id: str, package_id: str | None, kind: str,
              gross_amount_cents: int, settlement_state: str = "WITHHELD",
              payroll_period_id: str | None = None,
              audit: bool = True) -> dict:
    if kind not in _SALARY_KINDS:
        raise ValueError(f"unknown ledger kind: {kind}")
    entry = db.insert(
        "ledger_entries",
        {
            "annotator_id": annotator_id,
            "package_id": package_id,
            "payroll_period_id": payroll_period_id,
            "kind": kind,
            "gross_amount_cents": gross_amount_cents,
            "settlement_state": settlement_state,
        },
        with_version=False,
    )
    if audit and gross_amount_cents != 0 and kind in {
        "PIECE_RATE", "BONUS", "PENALTY", "ADJUSTMENT_UPHELD",
        "ADJUSTMENT_REJECTED", "TAX",
    }:
        write_audit(
            subject_kind="SALARY",
            subject_id=entry["id"],
            event_type="SALARY_ADJUSTMENT",
            from_value=None,
            to_value=str(gross_amount_cents),
        )
    return entry


def find_entries_for_package(package_id: str) -> list[dict]:
    return db.find_many("ledger_entries", package_id=package_id)


def find_entries_for_inspection(inspection_id: str) -> list[dict]:
    """Entries that derive from a particular inspection: we tag inspection_id on
    PIECE_RATE/BONUS/PENALTY entries to support reversal computations."""
    return [
        e for e in db.all_rows("ledger_entries")
        if e.get("inspection_id") == inspection_id
    ]
