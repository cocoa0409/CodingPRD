"""Logical clock setter and the periodic operations sweep (PRD §2.4, §2.6, §3.3)."""
from flask import Blueprint

import constants as C
from db import store
from errors import err
from clock import parse_iso, format_iso_ms, add_days
from middleware import authenticate, require_roles
from models import touch, recompute_credits_remaining
from response import success
from helpers import get_json_body
from services import (recompute_session_counts, recompute_session_posture,
                      promote_waitlist_head)

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()
    target = body.get("to_iso8601")
    if not isinstance(target, str) or not target:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is required")
    try:
        dt = parse_iso(target)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 UTC instant")
    store.clock.set(dt)
    # Advances the clock; runs no ops sweep. Returns empty data object.
    return success({})


@bp.post("/_ops/run")
def run_ops():
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    now = store.clock.now()

    # --- Entitlement expiry / renewal ---
    for ent in list(store.entitlements.values()):
        if ent["lifecycle_status"] != "ACTIVE":
            continue
        if ent["freeze_status"] != "UNFROZEN":
            continue
        if now < parse_iso(ent["cycle_end_utc"]):
            continue

        if ent["kind"] == "MEMBERSHIP" and ent["auto_renew"]:
            _renew_membership(ent)
        else:
            ent["lifecycle_status"] = "EXPIRED"
            touch(ent)

    # --- No-show strike window reset ---
    for member in list(store.members.values()):
        if member["no_show_strike_count"] <= 0:
            continue
        oldest = _oldest_no_show_time(member["id"])
        if oldest is None:
            continue
        if (now - oldest).total_seconds() > C.STRIKE_WINDOW_DAYS * 86400:
            member["no_show_strike_count"] = 0
            touch(member)

    # --- Waitlist promotion sweep ---
    for session in list(store.class_sessions.values()):
        if session["status"] in ("OPEN", "FULL"):
            recompute_session_counts(session)
            recompute_session_posture(session)
            while promote_waitlist_head(session) is not None:
                pass

    return success({})


def _renew_membership(ent):
    """Auto-renew an eligible MEMBERSHIP in place; rollover + cycle advance."""
    old_end = parse_iso(ent["cycle_end_utc"])
    new_start = old_end
    new_end = add_days(new_start, C.CYCLE_LENGTH_DAYS)
    ent["cycle_start_utc"] = format_iso_ms(new_start)
    ent["cycle_end_utc"] = format_iso_ms(new_end)

    # Rollover: carry min(credits_remaining, rollover_cap) into the new cycle.
    if ent["credits_total"] == -1:
        # Unlimited membership: credits stay unlimited; nothing to roll.
        ent["credits_used"] = 0
    else:
        remaining = ent["credits_total"] - ent["credits_used"]
        if remaining < 0:
            remaining = 0
        carried = min(remaining, ent["rollover_cap"])
        # After carrying, credits_remaining = credits_total + carried.
        # => credits_used = credits_total - (credits_total + carried) = -carried.
        ent["credits_used"] = -carried
    recompute_credits_remaining(ent)
    ent["frozen_days_consumed"] = 0
    touch(ent)


def _oldest_no_show_time(member_id):
    """Earliest booked_at_utc among the member's NO_SHOW reservations, as datetime."""
    times = []
    for r in store.reservations.values():
        if r["member_id"] == member_id and r["status"] == "NO_SHOW":
            try:
                times.append(parse_iso(r["booked_at_utc"]))
            except (ValueError, TypeError):
                continue
    if not times:
        return None
    return min(times)
