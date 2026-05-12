"""Doctor matching selector (calculations.doctor_match_selector)."""

from __future__ import annotations

import db


def doctor_live_load(doctor_id: str) -> int:
    """Count of Consultation rows for the doctor with session_status in QUEUED/ACCEPTED/IN_PROGRESS."""
    active_states = {"QUEUED", "ACCEPTED", "IN_PROGRESS"}
    return sum(
        1 for c in db.all_rows("consultations")
        if c.get("doctor_id") == doctor_id and c.get("session_status") in active_states
    )


def _doctor_passes_filter(doc, patient, recommended_dept_code, dm_disease_codes):
    """Doctor eligibility predicate (see SCAFFOLD §1.3 calculations.doctor_match_selector)."""
    if doc.get("department_code") != recommended_dept_code:
        return False
    if patient.get("region_code") not in (doc.get("licensed_region_codes") or []):
        return False
    if doc.get("status") != "AVAILABLE":
        return False
    specialty_set = set(doc.get("specialty_codes") or [])
    if not specialty_set.intersection(set(dm_disease_codes or [])):
        return False
    return True


def find_department_disease_codes(department_code: str):
    """Return the disease_codes attached to the given DepartmentMapping; first match by triage_priority then id."""
    mappings = [
        m for m in db.all_rows("department_mappings")
        if m.get("department_code") == department_code
    ]
    if not mappings:
        return []
    mappings.sort(key=lambda m: (m.get("triage_priority", 0), m.get("_seq", 0)))
    return mappings[0].get("disease_codes") or []


def select_doctor(patient, recommended_dept_code):
    """Run the full eligibility-plus-ranking pipeline. Returns the doctor row or None."""
    dm_diseases = find_department_disease_codes(recommended_dept_code)
    candidates = [
        d for d in db.all_rows("doctors")
        if _doctor_passes_filter(d, patient, recommended_dept_code, dm_diseases)
    ]
    pref_hospital = patient.get("preferred_hospital_id")
    if pref_hospital:
        candidates = [d for d in candidates if d.get("hospital_id") == pref_hospital]
    if not candidates:
        return None
    # rank: rating_score DESC, current_load ASC, id ASC
    candidates.sort(key=lambda d: (
        -float(d.get("rating_score") or 0),
        doctor_live_load(d["id"]),
        d["id"],
    ))
    return candidates[0]


def is_doctor_eligible(doctor, patient, recommended_dept_code):
    """Used by preferred-doctor variant."""
    dm_diseases = find_department_disease_codes(recommended_dept_code)
    return _doctor_passes_filter(doctor, patient, recommended_dept_code, dm_diseases)
