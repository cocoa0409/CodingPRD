"""Derived values, computed live (consistency_model: immediate)."""

import db


def restriction_level(event):
    """RED if any OPEN RED_FLAG, else YELLOW if any OPEN WATCH, else GREEN."""
    level = "GREEN"
    for a in db.alerts.values():
        if a["event_id"] == event["id"] and a["status"] == "OPEN":
            if a["severity"] == "RED_FLAG":
                return "RED"
            if a["severity"] == "WATCH":
                level = "YELLOW"
    return level


def event_approved_combatant_count(event):
    n = 0
    for p in db.participants.values():
        if p["event_id"] != event["id"]:
            continue
        if p["status"] not in ("VETTED", "CHECKED_IN"):
            continue
        if p["impression_class"] != "COMBATANT":
            continue
        if p["unit_id"] is not None:
            u = db.units.get(p["unit_id"])
            if u is None or u["status"] != "APPROVED":
                continue
        n += 1
    return n


def unit_approved_combatant_count(unit):
    n = 0
    for p in db.participants.values():
        if p["unit_id"] != unit["id"]:
            continue
        if p["status"] in ("VETTED", "CHECKED_IN") and p["impression_class"] == "COMBATANT":
            n += 1
    return n


def area_allocated_units(area):
    total = 0
    if area["area_kind"] == "PARKING":
        for ps in db.passes.values():
            if ps["site_area_id"] == area["id"] and ps["status"] == "ACTIVE":
                total += ps["units_used"]
    else:
        for al in db.allocations.values():
            if al["site_area_id"] == area["id"] and al["status"] == "ACTIVE":
                total += al["units"]
    return total


def open_red_flag_exists(event):
    for a in db.alerts.values():
        if (
            a["event_id"] == event["id"]
            and a["status"] == "OPEN"
            and a["severity"] == "RED_FLAG"
        ):
            return True
    return False


def sorted_all(items):
    """Default list order: created_at ASC; insertion seq breaks clock ties."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
