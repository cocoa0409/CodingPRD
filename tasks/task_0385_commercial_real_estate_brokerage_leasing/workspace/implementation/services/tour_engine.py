"""Tour-related side effects: space holds and requirement bubble-up (PRD §3.4)."""
from datetime import datetime, timedelta

from db import db, touch
from services.recompute import recompute_property_available_sf

BUFFER = timedelta(minutes=30)


def parse_dt(s):
    """Parse an ISO 8601 UTC datetime. Returns aware datetime or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(txt)
    except ValueError:
        return None


def release_tour_hold(tour):
    """If the tour holds its space, release it: Space ON_HOLD -> AVAILABLE,
    clear held_by_tour_id, holds_space=false, recompute available_sf (PRD §3.4)."""
    if not tour.get("holds_space"):
        return
    sp = db.spaces.get(tour["space_id"])
    if sp is not None and sp["status"] == "ON_HOLD" and \
            sp.get("held_by_tour_id") == tour["id"]:
        sp["status"] = "AVAILABLE"
        sp["held_by_tour_id"] = None
        touch(sp)
        recompute_property_available_sf(sp["property_id"])
    tour["holds_space"] = False


def reconcile_requirement_touring(requirement_id):
    """TOURING -> OPEN when all tours leave CONFIRMED and no deal is open (PRD §3.3)."""
    req = db.requirements.get(requirement_id)
    if req is None or req["status"] != "TOURING":
        return
    any_confirmed = any(
        t["requirement_id"] == requirement_id and t["status"] == "CONFIRMED"
        for t in db.tours.values()
    )
    if any_confirmed:
        return
    any_open_deal = any(
        d["requirement_id"] == requirement_id and d["stage"] not in ("DEAD", "EXECUTED")
        for d in db.deals.values()
    )
    if any_open_deal:
        return
    req["status"] = "OPEN"
    touch(req)


def space_overlap_conflict(space_id, cand_start, cand_end, exclude_tour_id):
    """Buffered overlap on same Space (PRD §3.4 / §1.3 tour_space_overlap)."""
    for t in db.tours.values():
        if t["space_id"] != space_id or t["status"] != "CONFIRMED":
            continue
        if t["id"] == exclude_tour_id:
            continue
        t_start = parse_dt(t["window_start"])
        t_end = parse_dt(t["window_end"])
        if cand_start < t_end + BUFFER and cand_end > t_start - BUFFER:
            return True
    return False


def broker_overlap_conflict(tenant_broker_id, cand_start, cand_end, exclude_tour_id):
    """Pure half-open overlap, no buffer, same tenant broker (PRD §3.4)."""
    for t in db.tours.values():
        if t["tenant_broker_id"] != tenant_broker_id or t["status"] != "CONFIRMED":
            continue
        if t["id"] == exclude_tour_id:
            continue
        t_start = parse_dt(t["window_start"])
        t_end = parse_dt(t["window_end"])
        if cand_start < t_end and cand_end > t_start:
            return True
    return False
