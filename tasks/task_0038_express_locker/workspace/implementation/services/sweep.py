"""Long-stay sweep + clock advance."""

from clock import iso, now, parse_iso, CLOCK
from constants import LONG_STAY_THRESHOLD_HOURS
from db import DB
from errors import APIError, invalid_request


def advance_clock(payload: dict):
    seconds = payload.get("seconds")
    if seconds is None:
        raise invalid_request("seconds required")
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        raise invalid_request("seconds must be a number")
    if s < 0:
        raise invalid_request("seconds must be >= 0")
    new_now = CLOCK.advance_seconds(s)
    return {"now": iso(new_now)}


def run_sweep():
    """Process Parcels in DEPOSITED ordered by deposited_at ASC, then id ASC."""
    n = now()
    threshold = LONG_STAY_THRESHOLD_HOURS * 3600
    candidates = [p for p in DB.parcels.values() if p.get("status") == "DEPOSITED"]
    candidates.sort(key=lambda p: (p.get("deposited_at") or "", p["id"]))
    transitioned = 0
    for p in candidates:
        dep = p.get("deposited_at")
        if not dep:
            continue
        try:
            dep_dt = parse_iso(dep)
        except Exception:
            continue
        elapsed = (n - dep_dt).total_seconds()
        if elapsed >= threshold:
            p["status"] = "LONG_STAY"
            from services.util import stamp_update
            stamp_update(p)
            DB.parcel_long_stay_at[p["id"]] = iso(now())
            transitioned += 1
        else:
            break
    return {"transitioned_count": transitioned}
