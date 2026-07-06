"""Shared cross-entity computed helpers and reverse lookups."""
from clock import parse_iso
from db import db
import calculations


def cooler_occupied_slots(cooler_id):
    """Count of STORED bodies pointing at this cooler (PRD §2.9)."""
    return sum(
        1 for b in db.bodies.values()
        if b.get("cooler_unit_id") == cooler_id and b["storage_status"] == "STORED"
    )


def cooler_occupancy_report(cooler):
    """Returns (occupied_slots, total_body_days)."""
    now = db.clock.now()
    occupied = 0
    total_days = 0
    for b in db.bodies.values():
        if b.get("cooler_unit_id") == cooler["id"] and b["storage_status"] == "STORED":
            occupied += 1
            intake_at = parse_iso(b["intake_at"])
            total_days += calculations.occupancy_body_days(intake_at, now)
    return occupied, total_days


def case_body(case_id):
    """Return the (single) Body for a case, or None (Body is 1:1 with Case)."""
    for b in db.bodies.values():
        if b["case_id"] == case_id:
            return b
    return None


def case_bodies(case_id):
    return [b for b in db.bodies.values() if b["case_id"] == case_id]


def case_autopsy_exam(case_id):
    """Return the autopsy exam for the case, if any (1:1). Prefer non-cancelled."""
    exams = [e for e in db.autopsy_exams.values() if e["case_id"] == case_id]
    if not exams:
        return None
    # Prefer a COMPLETED or SCHEDULED exam over a CANCELLED one.
    for e in exams:
        if e["exam_status"] != "CANCELLED":
            return e
    return exams[0]


def case_death_certificate(case_id):
    for c in db.death_certificates.values():
        if c["case_id"] == case_id:
            return c
    return None


def case_indigent_disposition(case_id):
    for d in db.indigent_dispositions.values():
        if d["case_id"] == case_id:
            return d
    return None


def case_next_of_kin(case_id):
    return [k for k in db.next_of_kin.values() if k["case_id"] == case_id]


def case_property_items(case_id):
    return [p for p in db.property_items.values() if p["case_id"] == case_id]


def case_has_verified_kin(case_id):
    return any(k["verified"] for k in db.next_of_kin.values() if k["case_id"] == case_id)


def billable_specimen_count(case_id):
    """Specimens for the case's body with chain_status in {SENT_TO_LAB, CONSUMED}."""
    body_ids = {b["id"] for b in case_bodies(case_id)}
    return sum(
        1 for s in db.specimens.values()
        if s["body_id"] in body_ids and s["chain_status"] in ("SENT_TO_LAB", "CONSUMED")
    )
