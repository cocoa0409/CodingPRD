"""Logical plant clock (PRD 2.4)."""

from db import STORES, set_clock, touch
from helpers import auth, body, f_dt
from response import success
from routes import make_bp

bp = make_bp("clock")


@bp.post("/plant/_clock/set_current_utc")
def set_current_utc():
    auth("PlantAdmin")
    b = body()
    raw, dt = f_dt(b, "to_iso8601")
    set_clock(dt)
    # Sweep 1: RELEASED lots expiring at or before the new time -> EXPIRED.
    expired_lot_ids = []
    for lot in STORES["additive_lots"].values():
        if lot["status"] == "RELEASED" and lot["_expires_dt"] <= dt:
            lot["status"] = "EXPIRED"
            touch(lot)
            expired_lot_ids.append(lot["id"])
    # Sweep 2: recompute age_days / turns_due for IN_ROOM aging units
    # (the same projection is also applied whenever a unit is read).
    from services import unit_age_days, unit_turns_due

    for unit in STORES["aging_units"].values():
        if unit["status"] == "IN_ROOM":
            unit["age_days"] = unit_age_days(unit)
            unit["turns_due"] = unit_turns_due(unit)
    return success({"now": raw, "expired_lot_ids": expired_lot_ids})
