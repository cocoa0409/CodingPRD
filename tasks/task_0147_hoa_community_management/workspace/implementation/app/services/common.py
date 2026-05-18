"""Shared helpers used by services and routes.

Keeps cross-cutting bookkeeping in one place: version bumps, OCC checks,
member overdue recompute, eligible_to_vote derivation, etc.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..errors import (
    APIError,
    err_invalid_state,
    err_not_found,
    err_version_conflict,
)
from ..store import store


def bump_version(entity: dict, now: datetime) -> None:
    """Increment version and refresh updated_at."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now


def check_version(entity: dict, supplied: Optional[int]) -> None:
    """Raise ERR_VERSION_CONFLICT if the supplied version does not match."""
    if supplied is None:
        return
    if not isinstance(supplied, int):
        raise err_version_conflict("version must be an integer")
    if supplied != entity.get("version", 1):
        raise err_version_conflict()


def require(collection: str, entity_id: Optional[str]):
    """Look up an entity by id; raise NOT_FOUND if missing."""
    if entity_id is None:
        raise err_not_found()
    s = store()
    coll = getattr(s, collection)
    obj = coll.get(entity_id)
    if obj is None:
        raise err_not_found()
    return obj


def compute_eligible_to_vote(member: dict) -> bool:
    s = store()
    owns_unit = any(
        u.get("owner_member_id") == member["id"] for u in s.units.values()
    )
    return owns_unit and member.get("total_overdue_amount_cents", 0) == 0


def recompute_member_overdue(member: dict) -> int:
    s = store()
    units = [u for u in s.units.values() if u["owner_member_id"] == member["id"]]
    unit_ids = {u["id"] for u in units}
    total = 0
    # Overdue charges contribute principal+late_fee-paid
    for ch in s.assessment_charges.values():
        if ch["unit_id"] in unit_ids and ch["status"] == "OVERDUE":
            outstanding = ch["principal_cents"] + ch["late_fee_cents"] - ch["paid_cents"]
            if outstanding > 0:
                total += outstanding
    # Fined violations whose fine has not yet been paid contribute fine_cents
    for v in s.violations.values():
        if v["unit_id"] in unit_ids and v["status"] == "FINED":
            if not v.get("fine_paid", False):
                total += v["fine_cents"]
    return total


def bump_member_overdue(member: dict) -> None:
    """Recompute total_overdue_amount_cents and refresh eligible_to_vote/version."""
    s = store()
    now = s.now()
    new_total = recompute_member_overdue(member)
    if member.get("total_overdue_amount_cents") != new_total:
        member["total_overdue_amount_cents"] = new_total
        bump_version(member, now)
    member["eligible_to_vote"] = compute_eligible_to_vote(member)


def sum_share_factors() -> Decimal:
    s = store()
    total = Decimal("0")
    for u in s.units.values():
        total += Decimal(str(u["share_factor"]))
    return total


def cycle_overdue_age_days(charge: dict) -> int:
    """Days a charge has spent in OVERDUE.

    Approximated by clock_now - parent_cycle.due_date when status == OVERDUE
    (a charge enters OVERDUE the instant clock crosses due_date).
    """
    s = store()
    cycle = s.assessment_cycles.get(charge["cycle_id"])
    if cycle is None:
        return 0
    if charge["status"] != "OVERDUE":
        return 0
    delta = s.now() - cycle["due_date"]
    return max(0, int(delta.total_seconds() // 86400))


def unit_has_60d_overdue_charge(unit_id: str) -> bool:
    s = store()
    for ch in s.assessment_charges.values():
        if ch["unit_id"] == unit_id and ch["status"] == "OVERDUE":
            if cycle_overdue_age_days(ch) >= 60:
                return True
    return False


def latest_adopted_reserve_study():
    s = store()
    adopted = [r for r in s.reserve_studies.values() if r["status"] == "ADOPTED"]
    if not adopted:
        return None
    # The PRD says "most recently adopted" — order by adopted-at proxy: updated_at.
    adopted.sort(key=lambda r: r.get("updated_at"))
    return adopted[-1]
