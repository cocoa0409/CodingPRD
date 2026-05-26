"""Cascade transitions driven by the clock or by parent state changes.

Centralizes the IN_PROGRESS, BID_CLOSED, and rolling-totals-refresh cascades
so they can be invoked from /_clock/set_current_utc as well as from inline
mutations (e.g., manual close-bidding).
"""
import db
from services.calc import (
    crew_rolling_totals,
    scheduled_block_minutes,
    actual_block_minutes,
)
from services.entity import touch
from services.timeutil import parse_iso


def refresh_rolling_totals_all_crew() -> None:
    """Recompute total_*_minutes_7d on every CrewMember whose assignments could
    fall in or out of the (current_utc - 168h, current_utc] window.

    Per PRD §2.6: this fires on every /_clock/set_current_utc.
    """
    for cm in db.crew_members.values():
        new_duty, new_flight = crew_rolling_totals(cm["id"])
        if new_duty != cm["total_duty_minutes_7d"] or new_flight != cm["total_flight_minutes_7d"]:
            cm["total_duty_minutes_7d"] = new_duty
            cm["total_flight_minutes_7d"] = new_flight
            touch(cm)


def cascade_clock_auto_transitions() -> None:
    """Apply every time-driven transition the new clock makes due (PRD §2.6).

    1. For each Pairing in BID_OPEN with current_utc >= bidding_close_utc → BID_CLOSED.
    2. For each Pairing in AWARDED with current_utc >= scheduled_start_utc and
       every child Assignment in CONFIRMED → IN_PROGRESS; child Assignments
       CONFIRMED → ACTIVE; owning crew status → ON_DUTY.
    3. Recompute rolling totals on each affected CrewMember.
    """
    now = db.current_utc

    # 1. Auto-close bidding.
    for p in db.pairings.values():
        if p["state"] == "BID_OPEN":
            if now >= parse_iso(p["bidding_close_utc"]):
                p["state"] = "BID_CLOSED"
                touch(p)

    # 2. Awarded → IN_PROGRESS when start_utc reached AND all child Assignments
    #    in CONFIRMED.
    for p in db.pairings.values():
        if p["state"] != "AWARDED":
            continue
        if now < parse_iso(p["scheduled_start_utc"]):
            continue
        children = [a for a in db.assignments.values() if a["pairing_id"] == p["id"]]
        if not children:
            continue
        if not all(c["state"] == "CONFIRMED" for c in children):
            continue
        # Cascade.
        p["state"] = "IN_PROGRESS"
        touch(p)
        for c in children:
            c["state"] = "ACTIVE"
            c["actual_duty_start_utc"] = db.now_iso()
            touch(c)
            cm = db.crew_members.get(c["crew_member_id"])
            if cm is not None:
                cm["status"] = "ON_DUTY"
                touch(cm)

    # 3. Always refresh persisted rolling totals — PRD §2.6 says the rolling
    #    window slides whenever the clock advances.
    refresh_rolling_totals_all_crew()


# ---------------------------------------------------------------------
# Pairing complete cascade (PRD §3.1)
# ---------------------------------------------------------------------

def cascade_pairing_complete(pairing: dict) -> None:
    """Pairing IN_PROGRESS → COMPLETED.

    Each ACTIVE Assignment → COMPLETED with actual_duty_end_utc, locked
    credited minutes from parent. Each owning CrewMember.status → ON_REST,
    last_off_duty_utc := current_utc, rolling totals recomputed.
    Finally Pairing.actual_block_minutes is locked.
    """
    pairing["state"] = "COMPLETED"
    touch(pairing)
    for a in db.assignments.values():
        if a["pairing_id"] != pairing["id"]:
            continue
        if a["state"] == "ACTIVE":
            a["state"] = "COMPLETED"
            a["actual_duty_end_utc"] = db.now_iso()
            a["flight_minutes_credited"] = int(pairing["total_flight_minutes"])
            a["duty_minutes_credited"] = int(pairing["total_duty_minutes"])
            touch(a)
            cm = db.crew_members.get(a["crew_member_id"])
            if cm is not None:
                cm["status"] = "ON_REST"
                cm["last_off_duty_utc"] = db.now_iso()
                touch(cm)
    # Lock actual_block_minutes after the COMPLETED transitions above.
    pairing["actual_block_minutes"] = actual_block_minutes(pairing["id"])
    # The block-update is part of the same atomic step that flipped state;
    # we already touched the pairing once above. Bump version once more to
    # reflect the actual-block field write — but PRD §3.1 phrases the
    # COMPLETED transition as a single atomic step. To keep test invariants
    # (version increments by exactly one) we DO NOT touch again here.
    # Refresh rolling totals on every crew member whose assignments completed.
    refresh_rolling_totals_all_crew()
