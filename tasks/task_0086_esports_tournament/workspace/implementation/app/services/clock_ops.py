"""Clock advance + sweeper. Triggers time-gated transitions."""
from __future__ import annotations

from typing import Any

from ..clock import CLOCK, format_iso, parse_iso
from ..errors import ApiError
from ..store import bump_version, get_store


def advance_clock(body: dict[str, Any]) -> dict[str, Any]:
    if "to" not in body:
        raise ApiError("ERR_BAD_REQUEST", "Missing 'to' field.")
    new_dt = parse_iso(body["to"])
    CLOCK.set(new_dt)
    # Trigger time-gated transitions
    _run_time_cascades()
    return {"now": format_iso(CLOCK.now)}


def run_sweeper() -> dict[str, Any]:
    _run_time_cascades()
    return {}


def _run_time_cascades() -> None:
    store = get_store()
    # 1) Tournaments whose roster_lock_deadline has passed → ROSTER_LOCKED
    for t in store.tournaments.values():
        if t["status"] != "REGISTRATION_OPEN":
            continue
        try:
            deadline = parse_iso(t["roster_lock_deadline"])
        except Exception:
            continue
        if CLOCK.now >= deadline:
            # Apply cascade
            for reg in store.team_registrations.values():
                if reg["tournament_id"] != t["id"]:
                    continue
                if reg["status"] in {"DRAFT", "FEE_PENDING"}:
                    reg["status"] = "WITHDRAWN"
                    bump_version(reg)
            t["status"] = "ROSTER_LOCKED"
            bump_version(t)

    # 2) Transfer offers whose window has closed → EXPIRED
    for o in store.transfer_offers.values():
        if o["status"] != "PROPOSED":
            continue
        w = store.transfer_windows.get(o["window_id"])
        if w is None:
            continue
        try:
            closes_at = parse_iso(w["closes_at"])
        except Exception:
            continue
        if CLOCK.now >= closes_at:
            o["status"] = "EXPIRED"
            bump_version(o)

    # 3) Contracts whose term_end has passed → EXPIRED
    for c in store.player_contracts.values():
        if c["status"] != "ACTIVE":
            continue
        try:
            term_end = parse_iso(c["term_end"])
        except Exception:
            continue
        if CLOCK.now >= term_end:
            c["status"] = "EXPIRED"
            bump_version(c)
