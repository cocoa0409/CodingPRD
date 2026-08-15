"""Seat-open handling: waitlist promotion (PUBLISHED) and float-pool backfill (RACE_DAY)."""
from datetime import timedelta
from decimal import Decimal

from db import store
from util import logical_now, parse_dt, format_iso
from services import core
from services.core import make_record, touch, update_shift_posture, confirmed_count


def _passes_gates(volunteer, role, shift, now):
    """Soft version of the safety gauntlet for promotion/backfill candidate filtering."""
    if volunteer["status"] != "ELIGIBLE":
        return False
    if volunteer["age_years_on_event"] < role["min_age_years"]:
        return False
    req_skill = role["required_skill"]
    if req_skill != "NONE" and req_skill not in (volunteer.get("skill_tags") or []):
        return False
    module = role["required_training_module"]
    if module != "NONE" and not core.training_current(volunteer["id"], module, now):
        return False
    # overlap check
    for su in store.signups.values():
        if (
            su["volunteer_id"] == volunteer["id"]
            and su["status"] in {"APPROVED", "CONFIRMED"}
            and su["shift_id"] != shift["id"]
        ):
            other = store.shifts.get(su["shift_id"])
            if other and core.shifts_overlap(shift, other):
                return False
    return True


def _set_confirm_by(signup, shift, now):
    """confirm_by_at = min(approved_at + 48h, shift.start_at - 1h)."""
    start = parse_dt(shift["start_at"])
    a = now + timedelta(hours=48)
    b = start - timedelta(hours=1)
    signup["confirm_by_at"] = format_iso(min(a, b))


def _try_waitlist_promotion(shift, now):
    candidates = []
    role = store.role_catalog_entries.get(shift["role_entry_id"])
    for su in store.signups.values():
        if su["shift_id"] == shift["id"] and su["status"] == "WAITLISTED":
            vol = store.volunteers.get(su["volunteer_id"])
            if vol is None:
                continue
            if _passes_gates(vol, role, shift, now):
                candidates.append((su, vol))
    if not candidates:
        return
    # rank: is_returning DESC, requested_at ASC, volunteer.created_at ASC
    candidates.sort(key=lambda pair: (
        0 if pair[1]["is_returning"] else 1,
        pair[0]["requested_at"],
        pair[1]["created_at"],
    ))
    su, _vol = candidates[0]
    su["status"] = "APPROVED"
    su["origin"] = "WAITLIST_PROMOTION"
    su["approved_at"] = format_iso(now)
    _set_confirm_by(su, shift, now)
    touch(su)
    update_shift_posture(shift)


def _volunteer_hours_worked(volunteer_id, event_id):
    """Sum of credited_hours over the volunteer's hour logs in any status except REJECTED."""
    total = Decimal(0)
    signup_ids = {
        su["id"] for su in store.signups.values()
        if su["volunteer_id"] == volunteer_id and su["event_id"] == event_id
    }
    for log in store.hour_logs.values():
        if log["signup_id"] in signup_ids and log["status"] != "REJECTED":
            total += Decimal(log["credited_hours"])
    return total


def _try_float_pool_backfill(shift, freed_signup, now):
    role = store.role_catalog_entries.get(shift["role_entry_id"])
    candidates = []
    for vol in store.volunteers.values():
        if vol["event_id"] != shift["event_id"]:
            continue
        if not vol.get("float_opt_in"):
            continue
        if not _passes_gates(vol, role, shift, now):
            continue
        # one active signup per (volunteer, shift) — cannot already hold active signup on this shift
        has_active = any(
            su["volunteer_id"] == vol["id"]
            and su["shift_id"] == shift["id"]
            and su["status"] in core.NON_TERMINAL_SIGNUP
            for su in store.signups.values()
        )
        if has_active:
            continue
        hours = _volunteer_hours_worked(vol["id"], shift["event_id"])
        candidates.append((vol, hours))
    if not candidates:
        shift["understaffed_alert"] = True
        touch(shift)
        return
    # rank: fewest hours ASC, then volunteer.created_at ASC
    candidates.sort(key=lambda pair: (pair[1], pair[0]["created_at"]))
    vol = candidates[0][0]
    su = make_record({
        "event_id": shift["event_id"],
        "volunteer_id": vol["id"],
        "shift_id": shift["id"],
        "status": "CONFIRMED",
        "origin": "FLOAT_POOL_BACKFILL",
        "replaces_signup_id": freed_signup["id"] if freed_signup else None,
        "is_captain": False,
        "requested_at": format_iso(now),
        "approved_at": None,
        "confirm_by_at": None,
        "confirmed_at": format_iso(now),
        "checked_in_at": None,
        "checked_out_at": None,
    })
    store.signups[su["id"]] = su
    update_shift_posture(shift)


def seat_open_handling(shift, freed_signup=None):
    """Fired after confirmed_count drops below required_headcount.
    PUBLISHED -> waitlist promotion; RACE_DAY within 90min of shift start -> float backfill.
    Safe to call unconditionally; it no-ops when the shift is full or event phase forbids."""
    shift["confirmed_count"] = confirmed_count(shift["id"])
    if shift["confirmed_count"] >= shift["required_headcount"]:
        update_shift_posture(shift)
        return
    ev = store.events.get(shift["event_id"])
    if ev is None:
        return
    now = logical_now()
    if ev["status"] == "PUBLISHED" and shift["status"] in {"OPEN", "FULL"}:
        _try_waitlist_promotion(shift, now)
    elif ev["status"] == "RACE_DAY" and shift["status"] == "IN_PROGRESS":
        start = parse_dt(shift["start_at"])
        if now <= start + timedelta(minutes=90):
            _try_float_pool_backfill(shift, freed_signup, now)
    update_shift_posture(shift)
