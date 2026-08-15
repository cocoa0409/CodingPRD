"""In-memory store and the logical clock.

The store starts EMPTY on every boot. No seeding of any entity is permitted;
tests construct all preconditions through the declared API surface.
"""

from datetime import datetime, timezone


class _LogicalClock:
    """Server-side logical clock. Starts at exactly 2026-08-01T00:00:00Z and
    is only ever moved by POST /emergency/_clock/set_current_utc."""

    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = _LogicalClock()

store = {
    "staff_members": {},
    "hazard_assessments": {},
    "plan_revisions": {},
    "exercises": {},
    "after_action_reports": {},
    "improvement_tasks": {},
    "incidents": {},
    "command_assignments": {},
    "callback_requests": {},
    "supply_items": {},
    "stock_transactions": {},
    "sites": {},
    "patients": {},
    "inquiries": {},
    "reports": {},
}
