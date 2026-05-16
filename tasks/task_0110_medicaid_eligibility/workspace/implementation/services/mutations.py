"""Generic write-side helpers for stamping created/updated/version fields and
for triggering parent-resource bumps when child writes change a derived value
(PRD §2.4 and §2.8)."""

from core.clock import CLOCK
from core.store import STORE
from core.timeutils import iso_format


def stamp_create(row: dict, append_only: bool = False) -> dict:
    row["created_at"] = CLOCK.now_iso()
    if not append_only:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def bump(row: dict):
    """Mutation: refresh updated_at and increment version. Used on Household
    when its derived fields change, and on any state-bearing entity on transition."""
    row["updated_at"] = CLOCK.now_iso()
    row["version"] = int(row.get("version", 0)) + 1


def bump_household(household_id: str):
    h = STORE.households.get(household_id)
    if h is not None:
        bump(h)


def recompute_household_active_count(household_id: str):
    """Recompute Household.active_enrollment_count synchronously.

    Per PRD §2.8 a change to active_enrollment_count is a mutation of the
    household and bumps updated_at/version. We don't store the count as a
    field — projections.project_household derives it on read — but we still
    need to bump the household so OCC reflects the change.
    """
    bump_household(household_id)
