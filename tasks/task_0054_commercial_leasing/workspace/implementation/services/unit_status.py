"""Unit status derivation per §3.1."""
from clock import now, parse_iso, to_utc_midnight
import db


_ACTIVE_LEASE_STATES = {"SIGNED", "ACTIVE", "AMENDMENT_PENDING", "TERMINATING"}


def derive_status(unit: dict) -> str:
    """Compute the unit's derived status per §3.1 priority cascade."""
    # 1) split or merge retirement → RETIRED
    if unit.get("_retired"):
        return "RETIRED"
    # 2) renovation interval active today
    rs = unit.get("renovation_start_date")
    re = unit.get("renovation_end_date")
    if rs and re:
        today = to_utc_midnight(now())
        rs_dt = parse_iso(rs)
        re_dt = parse_iso(re)
        if rs_dt <= today <= re_dt:
            return "UNDER_RENOVATION"
    # 3) any lease on this unit in SIGNED/ACTIVE/AMENDMENT_PENDING/TERMINATING
    for le in db.leases.values():
        if le.get("unit_id") == unit["id"] and le.get("status") in _ACTIVE_LEASE_STATES:
            return "LEASED"
    # 4) explicit reservation flag
    if unit.get("_reserved"):
        return "RESERVED"
    return "VACANT"


def update_status(unit: dict) -> None:
    """Refresh the persisted unit['status'] field based on the current data."""
    unit["status"] = derive_status(unit)


def update_unit_by_id(unit_id: str) -> None:
    u = db.units.get(unit_id)
    if u is not None:
        update_status(u)


def update_all() -> None:
    for u in db.units.values():
        update_status(u)
