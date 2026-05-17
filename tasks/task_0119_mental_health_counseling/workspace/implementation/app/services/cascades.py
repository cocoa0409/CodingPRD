"""Cascade routines — these are the side effects that fan out across resources.

Conventions:
  - Each function takes the live store and mutates rows in place.
  - Every mutated resource (with version) has its updated_at refreshed and version += 1 EXACTLY ONCE
    per cascade pass.
  - Callers are responsible for invoking from within the appropriate locked section.
"""
from __future__ import annotations

from typing import Any

from ..clock import now
from .calculations import (
    licensure_exam_eligible,
)


def bump(row: dict[str, Any]) -> None:
    """Refresh updated_at and increment version by 1 (for common-field entities only)."""
    if "version" in row:
        row["updated_at"] = now()
        row["version"] = row["version"] + 1


# ---- Helpers used across cascades -------------------------------------------


def _therapist_has_active_license_for_state(store, therapist_id: str, state_code: str) -> bool:
    """Return True iff a covering license exists for `state_code` directly or via PSYPACT."""
    therapist = store.therapists.get(therapist_id)
    if therapist is None:
        return False

    active_licenses = [
        lic for lic in store.state_licenses.values()
        if lic["therapist_id"] == therapist_id and lic["status"] == "ACTIVE"
    ]
    # Direct license for this state
    if any(lic["state_code"] == state_code for lic in active_licenses):
        return True
    # PSYPACT path: enrolled, target state is PSYPACT, and at least one active license in a PSYPACT state.
    from .calculations import PSYPACT_STATES
    if therapist.get("psypact_enrolled") and state_code in PSYPACT_STATES:
        if any(lic["state_code"] in PSYPACT_STATES for lic in active_licenses):
            return True
    return False


def _therapist_has_any_active_license(store, therapist_id: str) -> bool:
    return any(
        lic["therapist_id"] == therapist_id and lic["status"] == "ACTIVE"
        for lic in store.state_licenses.values()
    )


# ---- Appointment hold/unhold cascades ---------------------------------------

def hold_future_scheduled_for_therapist(store, therapist_id: str, reason: str) -> None:
    """Move every future SCHEDULED appointment for this therapist into HELD."""
    current = now()
    for appt in store.appointments.values():
        if appt["therapist_id"] != therapist_id:
            continue
        if appt["status"] != "SCHEDULED":
            continue
        if appt["scheduled_start"] <= current:
            continue
        appt["status"] = "HELD"
        appt["hold_reason"] = reason
        bump(appt)


def unhold_appointments_for_therapist_license_gap(store, therapist_id: str) -> None:
    """Cascade unhold: appointments HELD due to LICENSE_GAP for this therapist return to SCHEDULED."""
    for appt in store.appointments.values():
        if appt["therapist_id"] != therapist_id:
            continue
        if appt["status"] != "HELD":
            continue
        if appt.get("hold_reason") != "LICENSE_GAP":
            continue
        # Only unhold if therapist now has coverage AND is not suspended.
        therapist = store.therapists.get(therapist_id)
        if therapist is None:
            continue
        if therapist["credential_status"] != "ACTIVE":
            continue
        if not _therapist_has_active_license_for_state(store, therapist_id, appt["patient_state_on_day"]):
            continue
        appt["status"] = "SCHEDULED"
        appt["hold_reason"] = None
        bump(appt)


def hold_future_for_therapist_lacking_coverage(store, therapist_id: str) -> None:
    """After a license expiry/revocation: any future SCHEDULED appointment for this therapist
    that no longer has license coverage for its patient_state_on_day transitions to HELD/LICENSE_GAP.
    """
    current = now()
    for appt in store.appointments.values():
        if appt["therapist_id"] != therapist_id:
            continue
        if appt["status"] != "SCHEDULED":
            continue
        if appt["scheduled_start"] <= current:
            continue
        if _therapist_has_active_license_for_state(store, therapist_id, appt["patient_state_on_day"]):
            continue
        appt["status"] = "HELD"
        appt["hold_reason"] = "LICENSE_GAP"
        bump(appt)


def hold_future_for_patient_safety(store, patient_id: str) -> None:
    """Patient.safety_plan_required just became true → future SCHEDULED appointments → HELD/SAFETY_PLAN_MISSING."""
    current = now()
    for appt in store.appointments.values():
        if appt["patient_id"] != patient_id:
            continue
        if appt["status"] != "SCHEDULED":
            continue
        if appt["scheduled_start"] <= current:
            continue
        appt["status"] = "HELD"
        appt["hold_reason"] = "SAFETY_PLAN_MISSING"
        bump(appt)


def unhold_for_patient_safety(store, patient_id: str) -> None:
    """SafetyPlan ACTIVE just minted → unhold every appointment HELD/SAFETY_PLAN_MISSING for this patient."""
    for appt in store.appointments.values():
        if appt["patient_id"] != patient_id:
            continue
        if appt["status"] != "HELD":
            continue
        if appt.get("hold_reason") != "SAFETY_PLAN_MISSING":
            continue
        appt["status"] = "SCHEDULED"
        appt["hold_reason"] = None
        bump(appt)


# ---- Clock-advance cascade --------------------------------------------------

def expire_due_licenses_and_cascade(store) -> None:
    """Step through every ACTIVE license; expire any whose expires_on <= current clock,
    then cascade-hold appointments for any therapist that lost coverage."""
    current = now()
    expired_for_therapists: set[str] = set()
    for lic in list(store.state_licenses.values()):
        if lic["status"] != "ACTIVE":
            continue
        if lic["expires_on"] <= current:
            lic["status"] = "EXPIRED"
            bump(lic)
            expired_for_therapists.add(lic["therapist_id"])
    # Re-evaluate per affected therapist; HOLDing only when coverage now missing.
    for tid in expired_for_therapists:
        hold_future_for_therapist_lacking_coverage(store, tid)


# ---- Supervision-hour ledger helpers ----------------------------------------

def adjust_supervision_hours(store, therapist_id: str, delta) -> None:
    """delta is a Decimal (signed). Recomputes licensure_exam_eligible afterwards."""
    from .calculations import compute_new_accrued
    therapist = store.therapists.get(therapist_id)
    if therapist is None:
        return
    new_total = compute_new_accrued(therapist["supervision_hours_accrued"], delta)
    therapist["supervision_hours_accrued"] = new_total
    therapist["licensure_exam_eligible"] = licensure_exam_eligible(
        new_total, therapist["credential_status"]
    )
    bump(therapist)
