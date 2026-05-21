"""In-memory data store for all Travel & Expense entities."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional


class _Store:
    """Process-wide singleton holding every entity collection."""

    def __init__(self) -> None:
        self.employees: Dict[str, dict] = {}
        self.per_diem_rates: Dict[str, dict] = {}
        self.trips: Dict[str, dict] = {}
        self.virtual_cards: Dict[str, dict] = {}
        self.expense_reports: Dict[str, dict] = {}
        self.expense_lines: Dict[str, dict] = {}
        self.receipts: Dict[str, dict] = {}
        self.oop_approvals: Dict[str, dict] = {}

        # Logical clock for /_clock/advance — starts at 2024-01-01T00:00:00Z so
        # tests have plenty of forward and backward room.
        self.logical_now: datetime = datetime(2024, 1, 1, tzinfo=timezone.utc)

    # ------------------------------------------------------------------
    # Convenience helpers.
    # ------------------------------------------------------------------
    def lines_for_report(self, report_id: str) -> List[dict]:
        return [
            line
            for line in self.expense_lines.values()
            if line["report_id"] == report_id
        ]

    def reports_for_trip(self, trip_id: str) -> List[dict]:
        return [
            r for r in self.expense_reports.values() if r["trip_id"] == trip_id
        ]

    def cards_for_trip(self, trip_id: str) -> List[dict]:
        return [
            c for c in self.virtual_cards.values() if c["trip_id"] == trip_id
        ]

    def oop_for_line(self, line_id: str) -> List[dict]:
        return [
            a
            for a in self.oop_approvals.values()
            if a["expense_line_id"] == line_id
        ]


store = _Store()
