"""Intake sections: lazy expiry materialisation and the dual-variant score."""

from datetime import timedelta

import config
from clock import clock, parse_instant
from store import db, touch


def patient_sections(patient_id):
    return [s for s in db.intake_sections.values() if s["patient_id"] == patient_id]


def materialise_section(section):
    """ATTESTED -> EXPIRED once the logical clock reaches or passes expires_at."""
    if section["status"] != "ATTESTED" or not section.get("expires_at"):
        return False
    expires = parse_instant(section["expires_at"])
    if expires is not None and clock.now() >= expires:
        section["status"] = "EXPIRED"
        touch(section)
        return True
    return False


def booking_contribution(section):
    weight = config.INTAKE_SECTION_WEIGHTS[section["section_type"]]
    if section["status"] == "ATTESTED":
        return weight
    if section["status"] == "SUBMITTED":
        return weight // config.INTAKE_SUBMITTED_WEIGHT_DIVISOR
    return 0


def protocol_contribution(section):
    if section["status"] == "ATTESTED":
        return config.INTAKE_SECTION_WEIGHTS[section["section_type"]]
    return 0


def recompute_scores(patient):
    sections = patient_sections(patient["id"])
    booking = sum(booking_contribution(s) for s in sections)
    protocol = sum(protocol_contribution(s) for s in sections)
    changed = (
        patient.get("intake_booking_score") != booking
        or patient.get("intake_protocol_score") != protocol
    )
    patient["intake_booking_score"] = booking
    patient["intake_protocol_score"] = protocol
    if changed:
        touch(patient)


def materialise_patient_intake(patient):
    """Bring expiry up to date, then recompute both scores (PRD 2.4)."""
    if patient is None:
        return
    for section in patient_sections(patient["id"]):
        materialise_section(section)
    recompute_scores(patient)


def expiry_instant(attested_at):
    parsed = parse_instant(attested_at)
    if parsed is None:
        return None
    return parsed + timedelta(days=config.INTAKE_SECTION_VALIDITY_DAYS)
