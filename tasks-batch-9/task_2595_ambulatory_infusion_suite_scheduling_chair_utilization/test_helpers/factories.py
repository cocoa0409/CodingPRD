"""Payload factories: one per creating endpoint, input fields only.

Every factory returns a fresh dict of valid input and accepts keyword overrides,
including ``None`` values, which are dropped so a caller can omit an optional
field to exercise its default.
"""

from typing import Any, Dict

from .constants import (
    CENTER_DEFAULTS,
    DEFAULT_APPROVED_UNITS,
    DEFAULT_PAYER_NAME,
    DRUG_FLOORED_DEFAULTS,
    DRUG_GATE_DEFAULTS,
    DRUG_SHORT_DEFAULTS,
    NURSE_DEFAULTS,
    PATIENT_WEIGHT_KG,
    PLAN_MID_DOSE_MG_PER_KG,
)
from .types import (
    AdverseEventAction,
    BookingClass,
    ChairStatus,
    ChairType,
    DoseTier,
    ReminderChannel,
)

_UNSET = object()


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key explicitly set to ``None``."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Infusion center / chair / nurse
# ---------------------------------------------------------------------------
def make_center_payload(**overrides) -> Dict[str, Any]:
    return _merge(CENTER_DEFAULTS, overrides)


def make_minimal_center_payload(**overrides) -> Dict[str, Any]:
    """Only the three mandatory fields, so every policy dial takes its default."""
    return _merge(
        {"name": "Minimal Suite", "open_minute": 480, "close_minute": 1140}, overrides
    )


def make_chair_payload(center_id: str, label: str = "A1", **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "center_id": center_id,
            "label": label,
            "chair_type": ChairType.STANDARD,
            "status": ChairStatus.AVAILABLE,
            "reserved_for_urgent": False,
        },
        overrides,
    )


def make_nurse_payload(center_id: str, **overrides) -> Dict[str, Any]:
    return _merge(dict(NURSE_DEFAULTS, center_id=center_id), overrides)


# ---------------------------------------------------------------------------
# Drug catalogue and inventory
# ---------------------------------------------------------------------------
def make_drug_payload(**overrides) -> Dict[str, Any]:
    """The standing lab-gated product: base 120 / floor 90 / premed 30."""
    return _merge(DRUG_GATE_DEFAULTS, overrides)


def make_ungated_drug_payload(**overrides) -> Dict[str, Any]:
    """A short, ungated, one-acuity-point product."""
    return _merge(DRUG_SHORT_DEFAULTS, overrides)


def make_floored_drug_payload(**overrides) -> Dict[str, Any]:
    """A product whose administration floor beats its escalated base time."""
    return _merge(DRUG_FLOORED_DEFAULTS, overrides)


def make_biosimilar_payload(reference_drug_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Infliximab-Bio",
            "is_biosimilar": True,
            "reference_drug_id": reference_drug_id,
            "base_administration_minutes": 120,
            "min_administration_minutes": 90,
            "premedication_minutes": 30,
            "observation_minutes_first_dose": 60,
            "observation_minutes_subsequent": 30,
            "acuity_points": 2,
            "prep_stability_minutes": 240,
            "unit_cost_cents": 60000,
            "requires_lab_gate": False,
        },
        overrides,
    )


def make_drug_lot_payload(
    drug_id: str,
    lot_number: str = "LOT-0001",
    units_received: int = 10,
    expires_on: str = "2026-12-01T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "drug_id": drug_id,
            "lot_number": lot_number,
            "units_received": units_received,
            "expires_on": expires_on,
        },
        overrides,
    )


def make_lot_adjustment_payload(
    units_delta: int, expected_drug_lot_version: int, reason: str = "Physical count", **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "units_delta": units_delta,
            "reason": reason,
            "expected_drug_lot_version": expected_drug_lot_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Patients and regimens
# ---------------------------------------------------------------------------
def make_patient_payload(
    mrn: str = "MRN-0001", full_name: str = "Pat One", **overrides
) -> Dict[str, Any]:
    return _merge(
        {"mrn": mrn, "full_name": full_name, "weight_kg": PATIENT_WEIGHT_KG}, overrides
    )


def make_treatment_plan_payload(
    patient_id: str, drug_id: str, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "patient_id": patient_id,
            "drug_id": drug_id,
            "dose_mg_per_kg": PLAN_MID_DOSE_MG_PER_KG,
            "total_cycles": 6,
            "premed_waived": False,
        },
        overrides,
    )


def make_plan_revision_payload(
    expected_treatment_plan_version: int,
    dose_mg_per_kg: float = 5,
    total_cycles: int = 4,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "dose_mg_per_kg": dose_mg_per_kg,
            "total_cycles": total_cycles,
            "expected_treatment_plan_version": expected_treatment_plan_version,
        },
        overrides,
    )


def make_resume_payload(reason: str = "Reviewed and cleared", **overrides) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


# ---------------------------------------------------------------------------
# Templates and appointments
# ---------------------------------------------------------------------------
def make_template_payload(
    center_id: str, drug_id: str, dose_tier: str = DoseTier.MID, **overrides
) -> Dict[str, Any]:
    return _merge(
        {"center_id": center_id, "drug_id": drug_id, "dose_tier": dose_tier}, overrides
    )


def make_appointment_payload(
    center_id: str,
    patient_id: str,
    treatment_plan_id: str,
    template_id: str,
    service_date: str = "2026-08-10",
    requested_start_minute: int = 540,
    cycle_number: int = 1,
    booking_class: str = BookingClass.ROUTINE,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "center_id": center_id,
            "patient_id": patient_id,
            "treatment_plan_id": treatment_plan_id,
            "template_id": template_id,
            "service_date": service_date,
            "requested_start_minute": requested_start_minute,
            "cycle_number": cycle_number,
            "booking_class": booking_class,
        },
        overrides,
    )


def make_reschedule_payload(
    expected_appointment_version: int,
    service_date: str = "2026-08-11",
    requested_start_minute: int = 600,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "service_date": service_date,
            "requested_start_minute": requested_start_minute,
            "expected_appointment_version": expected_appointment_version,
        },
        overrides,
    )


def make_cancel_payload(reason: str = "Patient request", **overrides) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


# ---------------------------------------------------------------------------
# Authorization, compounding, reactions, labs, reminders
# ---------------------------------------------------------------------------
def make_authorization_payload(
    payer_name: str = DEFAULT_PAYER_NAME, **overrides
) -> Dict[str, Any]:
    return _merge({"payer_name": payer_name}, overrides)


def make_approval_decision_payload(
    approved_units: int = DEFAULT_APPROVED_UNITS, **overrides
) -> Dict[str, Any]:
    return _merge({"decision": "APPROVED", "approved_units": approved_units}, overrides)


def make_pend_decision_payload(
    decision_reason: str = "More clinical justification required", **overrides
) -> Dict[str, Any]:
    return _merge({"decision": "PENDED", "decision_reason": decision_reason}, overrides)


def make_denial_decision_payload(
    decision_reason: str = "Not a covered indication", **overrides
) -> Dict[str, Any]:
    return _merge({"decision": "DENIED", "decision_reason": decision_reason}, overrides)


def make_preparation_payload(units_requested: int = 2, **overrides) -> Dict[str, Any]:
    return _merge({"units_requested": units_requested}, overrides)


def make_return_payload(reason: str = "Visit stood down", **overrides) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


def make_adverse_event_payload(
    grade: int = 2, action: str = AdverseEventAction.HOLD, **overrides
) -> Dict[str, Any]:
    return _merge({"grade": grade, "action": action}, overrides)


def make_close_review_payload(
    review_outcome: str = "RESUME_SAME_DRUG", **overrides
) -> Dict[str, Any]:
    return _merge({"review_outcome": review_outcome}, overrides)


def make_lab_result_payload(
    patient_id: str,
    collected_at: str = "2026-08-05T06:00:00Z",
    anc_value: float = 2.0,
    platelet_value: float = 200,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "patient_id": patient_id,
            "collected_at": collected_at,
            "anc_value": anc_value,
            "platelet_value": platelet_value,
        },
        overrides,
    )


def make_reminder_payload(
    channel: str = ReminderChannel.SMS, **overrides
) -> Dict[str, Any]:
    return _merge({"channel": channel}, overrides)


def make_reminder_response_payload(
    outcome: str = "CONFIRM_ATTENDANCE", **overrides
) -> Dict[str, Any]:
    return _merge({"outcome": outcome}, overrides)


# ---------------------------------------------------------------------------
# Operational capabilities
# ---------------------------------------------------------------------------
def make_clock_payload(current_utc: str, **overrides) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


def make_sweep_payload(service_date: str, **overrides) -> Dict[str, Any]:
    return _merge({"service_date": service_date}, overrides)


def make_history_payload(
    center_id: str,
    patient_id: str,
    treatment_plan_id: str,
    template_id: str,
    service_date: str,
    schedule_status: str,
    chair_minutes: int = 240,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "center_id": center_id,
            "patient_id": patient_id,
            "treatment_plan_id": treatment_plan_id,
            "template_id": template_id,
            "service_date": service_date,
            "schedule_status": schedule_status,
            "chair_minutes": chair_minutes,
        },
        overrides,
    )
