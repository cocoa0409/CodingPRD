"""Storage unit posture, excursion metrics, failure and return-to-service cascades."""
from datetime import datetime, timezone

import db
from clock import now
from services.common import touch, round2
from services.destruction import create_destruction_order

VIABILITY_LIMIT_DEG_MIN = 120.0


def unit_readings_sorted(unit_id):
    readings = [r for r in db.temperature_readings.values() if r["storage_unit_id"] == unit_id]
    readings.sort(key=lambda r: (r["recorded_at"], r["created_at"]))
    return readings


def recompute_excursions(unit):
    """Recompute peak_excursion_c and cumulative_degree_minutes over all readings."""
    readings = unit_readings_sorted(unit["id"])
    peak = 0.0
    cumulative = 0.0
    prev = None
    for r in readings:
        excess = r["temp_c"] - unit["warn_threshold_c"]
        if excess > peak:
            peak = excess
        if prev is not None and r["temp_c"] > unit["warn_threshold_c"]:
            minutes = (r["recorded_at"] - prev["recorded_at"]).total_seconds() / 60.0
            if minutes > 0:
                cumulative += excess * minutes
        prev = r
    unit["peak_excursion_c"] = round2(max(peak, 0.0))
    unit["cumulative_degree_minutes"] = round2(max(cumulative, 0.0))


def degree_minutes_in_window(unit, start, end):
    """Degree-minute accrual from readings in (start, end]-style quarantine window.

    Per the cumulative formula: for every reading strictly above warn threshold,
    accrue excess * minutes since previous reading. For a quarantine window we
    include readings with start < recorded_at <= end, spacing measured from the
    previous reading whenever it exists (even if the previous reading predates
    the window start).
    """
    readings = unit_readings_sorted(unit["id"])
    total = 0.0
    for i, r in enumerate(readings):
        if r["recorded_at"] <= start or r["recorded_at"] > end:
            continue
        if r["temp_c"] <= unit["warn_threshold_c"]:
            continue
        if i == 0:
            continue
        minutes = (r["recorded_at"] - readings[i - 1]["recorded_at"]).total_seconds() / 60.0
        if minutes <= 0:
            continue
        total += (r["temp_c"] - unit["warn_threshold_c"]) * minutes
    return total


def slots_of_unit(unit_id):
    return [s for s in db.storage_slots.values() if s["storage_unit_id"] == unit_id]


def fire_failure_cascade(unit):
    """Unit -> FAILURE: slots OFFLINE, future BOOKED reservations CANCELLED,
    aliquots IN_STORAGE -> QUARANTINED (stamped), specimens viability QUARANTINED."""
    current = now()
    unit_slot_ids = set()
    for slot in slots_of_unit(unit["id"]):
        unit_slot_ids.add(slot["id"])
        if slot["status"] == "AVAILABLE":
            slot["status"] = "OFFLINE"
            touch(slot)
        for res in db.slot_reservations.values():
            if (
                res["storage_slot_id"] == slot["id"]
                and res["status"] == "BOOKED"
                and res["ends_at"] > current
            ):
                res["status"] = "CANCELLED"
                touch(res)
    affected_specimens = set()
    for a in db.aliquots.values():
        if (
            a["storage_slot_id"] in unit_slot_ids
            and a["status"] == "IN_STORAGE"
        ):
            a["status"] = "QUARANTINED"
            a["quarantine_started_at"] = current
            touch(a)
            affected_specimens.add(a["specimen_id"])
    # Specimens directly housed in unit slots are quarantined too.
    for s in db.specimens.values():
        if s["storage_slot_id"] in unit_slot_ids and s["viability_status"] != "QUARANTINED":
            s["viability_status"] = "QUARANTINED"
            touch(s)
    for sp_id in affected_specimens:
        sp = db.specimens.get(sp_id)
        if sp and sp["viability_status"] != "QUARANTINED":
            sp["viability_status"] = "QUARANTINED"
            touch(sp)


def return_to_service_cascade(unit):
    """FAILURE -> OPERATIONAL: slots AVAILABLE, quarantined aliquots reviewed."""
    for slot in slots_of_unit(unit["id"]):
        if slot["status"] == "OFFLINE":
            slot["status"] = "AVAILABLE"
            touch(slot)
    current = now()
    for a in list(db.aliquots.values()):
        if a["status"] != "QUARANTINED":
            continue
        slot = db.storage_slots.get(a["storage_slot_id"])
        if slot is None or slot["storage_unit_id"] != unit["id"]:
            continue
        start = a.get("quarantine_started_at") or a["created_at"]
        if isinstance(start, str):
            start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        delta = degree_minutes_in_window(unit, start, current)
        if delta <= VIABILITY_LIMIT_DEG_MIN:
            a["status"] = "IN_STORAGE"
            a.pop("quarantine_started_at", None)
            touch(a)
            sp = db.specimens.get(a["specimen_id"])
            if sp is not None:
                still_quarantined = any(
                    x["specimen_id"] == sp["id"] and x["status"] == "QUARANTINED"
                    for x in db.aliquots.values()
                )
                if not still_quarantined and sp["viability_status"] == "QUARANTINED":
                    sp["viability_status"] = "USABLE"
                    touch(sp)
        else:
            a["status"] = "DESTRUCTION_PENDING"
            a.pop("quarantine_started_at", None)
            touch(a)
            sp = db.specimens.get(a["specimen_id"])
            if sp is not None:
                if sp["lifecycle_status"] in ("ACCESSIONED", "IN_STORAGE"):
                    sp["lifecycle_status"] = "DESTRUCTION_PENDING"
                    touch(sp)
                has_pending = any(
                    o["specimen_id"] == sp["id"] and o["status"] == "PENDING"
                    for o in db.destruction_orders.values()
                )
                if not has_pending:
                    create_destruction_order(sp["id"], "QUALITY_FAILURE", "system")
    # Specimens directly in slots of this unit with no quarantined children recover.
    unit_slot_ids = {s["id"] for s in slots_of_unit(unit["id"])}
    for sp in db.specimens.values():
        if (
            sp["storage_slot_id"] in unit_slot_ids
            and sp["viability_status"] == "QUARANTINED"
        ):
            still_quarantined = any(
                x["specimen_id"] == sp["id"] and x["status"] == "QUARANTINED"
                for x in db.aliquots.values()
            )
            if not still_quarantined:
                sp["viability_status"] = "USABLE"
                touch(sp)
