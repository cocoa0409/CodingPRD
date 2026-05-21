"""In-memory data store for all ESPP entities."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.utils import format_iso


class _Store:
    """Process-wide singleton holding every entity collection."""

    def __init__(self) -> None:
        self.plans: Dict[str, dict] = {}
        self.offering_periods: Dict[str, dict] = {}
        self.enrollments: Dict[str, dict] = {}
        self.contributions: Dict[str, dict] = {}
        self.purchases: Dict[str, dict] = {}
        self.form_3922s: Dict[str, dict] = {}
        self.dispositions: Dict[str, dict] = {}

        # Singleton SystemClock. Start at epoch 2020-01-01T00:00:00Z so tests
        # have plenty of forward room.
        epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
        self.clock: Dict[str, Optional[str]] = {
            "current_time": format_iso(epoch),
            "last_sweep_at": None,
        }

        # Track who posted each contribution (operator id, by Contribution.id)
        # for the segregation-of-duties check.
        self.contribution_posters: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Convenience accessors used across services.
    # ------------------------------------------------------------------
    def list_offering_periods_for_plan(self, plan_id: str) -> List[dict]:
        return [op for op in self.offering_periods.values() if op["plan_id"] == plan_id]

    def list_enrollments_for_period(self, offering_period_id: str) -> List[dict]:
        return [
            e
            for e in self.enrollments.values()
            if e["offering_period_id"] == offering_period_id
        ]

    def list_contributions_for_enrollment(self, enrollment_id: str) -> List[dict]:
        return [
            c
            for c in self.contributions.values()
            if c["enrollment_id"] == enrollment_id
        ]

    def list_dispositions_for_purchase(self, purchase_id: str) -> List[dict]:
        return [
            d for d in self.dispositions.values() if d["purchase_id"] == purchase_id
        ]


# Process-wide singleton.
store = _Store()
