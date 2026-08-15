"""Environmental posture evaluation (scaffold §1.3 environmental_posture_evaluation)
and the zone -> item -> appointment cascade (PRD §2.6).
"""

from __future__ import annotations

from decimal import Decimal

import db

BREACH_STREAK_RESTRICT = 3
BREACH_STREAK_CLOSE = 6
CLEAN_STREAK_RECOVER = 3
SEVERE_TEMP_MARGIN_C = Decimal("4.0")
SEVERE_HUMIDITY_MARGIN_PCT = Decimal("15.0")

POSTURE_LEVEL = {"OPEN": 0, "RESTRICTED": 1, "CLOSED": 2}
LEVEL_POSTURE = {0: "OPEN", 1: "RESTRICTED", 2: "CLOSED"}


def compute_breach(zone: dict, temperature_c: Decimal, humidity_pct: Decimal) -> tuple[bool, bool]:
    """Asymmetric operators (pinned): temperature strict, humidity inclusive."""
    is_breach = (
        temperature_c > zone["temp_high_c"]
        or temperature_c < zone["temp_low_c"]
        or humidity_pct >= zone["humidity_high_pct"]
        or humidity_pct <= zone["humidity_low_pct"]
    )
    is_severe = (
        temperature_c >= zone["temp_high_c"] + SEVERE_TEMP_MARGIN_C
        or humidity_pct >= zone["humidity_high_pct"] + SEVERE_HUMIDITY_MARGIN_PCT
    )
    return is_breach, is_severe


def replay_posture(zone: dict) -> tuple[str, int]:
    """Deterministic replay over recent_readings ordered by
    (recorded_at ASC, created_at ASC, insertion seq ASC). Returns
    (posture, breach_streak)."""
    posture = "OPEN"
    breach_run = 0
    clean_run = 0
    ordered = sorted(
        zone["recent_readings"],
        key=lambda r: (r["_recorded_dt"], r["_created_at"], r["_seq"]),
    )
    for r in ordered:
        if r["is_severe"]:
            posture = "CLOSED"
            breach_run += 1
            clean_run = 0
        elif r["is_breach"]:
            breach_run += 1
            clean_run = 0
            if breach_run >= BREACH_STREAK_CLOSE:
                posture = "CLOSED"
            elif breach_run >= BREACH_STREAK_RESTRICT and posture == "OPEN":
                posture = "RESTRICTED"
            # 1-2 breaches: hysteresis — posture unchanged
        else:
            clean_run += 1
            breach_run = 0
            if clean_run >= CLEAN_STREAK_RECOVER:
                # step one level toward OPEN (never CLOSED -> OPEN directly)
                posture = LEVEL_POSTURE[max(0, POSTURE_LEVEL[posture] - 1)]
    return posture, breach_run


def _zone_hold_cascade(zone: dict) -> None:
    """Zone left OPEN: AVAILABLE items in the zone -> ZONE_HOLD; affected future
    CONFIRMED appointments -> NEEDS_RESCHEDULE (links 1 and 2)."""
    today = db.get_now().date()
    held_item_ids = set()
    for item in db.items.values():
        if item["status"] != "AVAILABLE":
            continue
        coll = db.collections.get(item["collection_id"])
        if coll is None or coll["storage_zone_id"] != zone["id"]:
            continue
        item["status"] = "ZONE_HOLD"
        db.touch(item)
        held_item_ids.add(item["id"])
    if not held_item_ids:
        return
    for appt in db.appointments.values():
        if appt["status"] != "CONFIRMED" or appt["_scheduled_date"] < today:
            continue
        req = db.requests.get(appt["research_request_id"])
        if req is None:
            continue
        if any(iid in held_item_ids for iid in req["item_ids"]):
            appt["status"] = "NEEDS_RESCHEDULE"
            db.touch(appt)


def _zone_release_cascade(zone: dict) -> None:
    """Zone returned to OPEN: its ZONE_HOLD items -> AVAILABLE. Appointments in
    NEEDS_RESCHEDULE are deliberately NOT auto-restored (pinned asymmetry)."""
    for item in db.items.values():
        if item["status"] != "ZONE_HOLD":
            continue
        coll = db.collections.get(item["collection_id"])
        if coll is None or coll["storage_zone_id"] != zone["id"]:
            continue
        item["status"] = "AVAILABLE"
        db.touch(item)


def apply_posture(zone: dict) -> None:
    """Replay readings, store posture/streak, and fire posture cascades."""
    old_posture = zone["posture"]
    new_posture, streak = replay_posture(zone)
    zone["posture"] = new_posture
    zone["breach_streak"] = streak
    if old_posture == "OPEN" and new_posture in ("RESTRICTED", "CLOSED"):
        _zone_hold_cascade(zone)
    elif new_posture == "OPEN" and old_posture in ("RESTRICTED", "CLOSED"):
        _zone_release_cascade(zone)
