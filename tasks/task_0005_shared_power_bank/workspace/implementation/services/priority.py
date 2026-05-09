"""Operator-task priority score (PRD §3.8)."""
from db import db


LOW_BATTERY_WEIGHT = 10
FAULTY_SLOT_WEIGHT = 5
OFFLINE_BONUS = 50
LOW_BATTERY_THRESHOLD = 30


def compute_priority_score(cabinet_id: str) -> int:
    cab = db.cabinets[cabinet_id]
    low_battery_count = sum(
        1
        for d in db.devices.values()
        if d.get("current_cabinet_id") == cabinet_id
        and d["status"] == "AVAILABLE"
        and d["battery_level"] < LOW_BATTERY_THRESHOLD
    )
    faulty_slot_count = sum(
        1 for s in db.slots.values()
        if s["cabinet_id"] == cabinet_id and s["slot_status"] == "FAULTY"
    )
    offline_bonus = OFFLINE_BONUS if cab["online_status"] == "OFFLINE" else 0
    return (LOW_BATTERY_WEIGHT * low_battery_count) + (FAULTY_SLOT_WEIGHT * faulty_slot_count) + offline_bonus
