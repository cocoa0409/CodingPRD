"""Payload builders, one per write endpoint.

Each builder returns a complete, valid body with sensible domain defaults and
accepts ``**overrides`` so a test can perturb exactly the field under
examination — or delete one by passing it as ``None`` and popping it, which the
required-field tests do.
"""

import itertools
from typing import Any, Dict, Optional

from .types import (
    BedType,
    CheckType,
    ConsentBasis,
    DischargeDecision,
    GenderCareCategory,
    GenderMixingPolicy,
    HoldType,
    InterventionType,
    LegalStatus,
    RequestedBy,
    SearchType,
    StaffRole,
    SurrogateAuthorityScope,
    SurrogateRelationship,
)

_LICENSE_SEQUENCE = itertools.count(1)
_MRN_SEQUENCE = itertools.count(1)


def unique_license_number(prefix: str = "LIC") -> str:
    """A license number no other clinician in this run will hold."""
    return f"{prefix}-2367-{next(_LICENSE_SEQUENCE):04d}"


def unique_mrn(prefix: str = "MRN") -> str:
    """A medical record number no other patient in this run will hold."""
    return f"{prefix}-2367-{next(_MRN_SEQUENCE):04d}"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Roster and physical plant
# ---------------------------------------------------------------------------


def clinician_payload(
    full_name: str = "Iris Nolan",
    staff_role: str = StaffRole.INTAKE_CLINICIAN.value,
    license_number: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": full_name,
            "staff_role": staff_role,
            "license_number": license_number or unique_license_number(),
        },
        overrides,
    )


def unit_payload(
    name: str = "Ward 4 North",
    gender_mixing_policy: str = GenderMixingPolicy.SEPARATE_BY_ROOM.value,
    seclusion_room_count: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "gender_mixing_policy": gender_mixing_policy,
            "seclusion_room_count": seclusion_room_count,
        },
        overrides,
    )


def bed_payload(
    unit_id: str,
    room_number: str = "401",
    wing_code: str = "A",
    bed_label: str = "401-A",
    bed_type: str = BedType.STANDARD.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "unit_id": unit_id,
            "room_number": room_number,
            "wing_code": wing_code,
            "bed_label": bed_label,
            "bed_type": bed_type,
        },
        overrides,
    )


def patient_payload(
    mrn: Optional[str] = None,
    legal_name: str = "Dana Whitlock",
    age_years: int = 34,
    gender_care_category: str = GenderCareCategory.FEMALE.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "mrn": mrn or unique_mrn(),
            "legal_name": legal_name,
            "age_years": age_years,
            "gender_care_category": gender_care_category,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Clinical assessment
# ---------------------------------------------------------------------------


def evaluation_payload(
    patient_id: str,
    danger_to_self: bool = True,
    danger_to_others: bool = False,
    grave_disability: bool = False,
    capacity_present: bool = False,
    clinical_summary: str = "Acute suicidal ideation with a stated plan.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "patient_id": patient_id,
            "danger_to_self": danger_to_self,
            "danger_to_others": danger_to_others,
            "grave_disability": grave_disability,
            "capacity_present": capacity_present,
            "clinical_summary": clinical_summary,
        },
        overrides,
    )


def hold_payload(
    patient_id: str,
    evaluation_id: str,
    hold_type: str = HoldType.EMERGENCY_72H.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "patient_id": patient_id,
            "evaluation_id": evaluation_id,
            "hold_type": hold_type,
        },
        overrides,
    )


def certification_payload(
    certification_note: str = "Criteria independently confirmed at the bedside.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"certification_note": certification_note}, overrides)


def rescind_payload(
    rescind_reason: str = "Patient no longer meets involuntary criteria.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"rescind_reason": rescind_reason}, overrides)


# ---------------------------------------------------------------------------
# Judicial track
# ---------------------------------------------------------------------------


def petition_payload(
    hold_id: str,
    requested_hold_type: str = HoldType.EXTENSION_14D.value,
    petition_grounds: str = "Continued grave disability without treatment.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "hold_id": hold_id,
            "requested_hold_type": requested_hold_type,
            "petition_grounds": petition_grounds,
        },
        overrides,
    )


def withdraw_payload(
    withdraw_reason: str = "Family agreed to a voluntary plan of care.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"withdraw_reason": withdraw_reason}, overrides)


def hearing_payload(
    petition_id: str,
    advocate_clinician_id: str,
    scheduled_start_at: str,
    duration_minutes: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "petition_id": petition_id,
            "advocate_clinician_id": advocate_clinician_id,
            "scheduled_start_at": scheduled_start_at,
            "duration_minutes": duration_minutes,
        },
        overrides,
    )


def hearing_outcome_payload(
    outcome: str,
    findings_note: str = "Findings entered on the record.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "findings_note": findings_note}, overrides)


# ---------------------------------------------------------------------------
# Admission track
# ---------------------------------------------------------------------------


def admission_payload(
    patient_id: str,
    evaluation_id: str,
    unit_id: str,
    requested_legal_status: str = LegalStatus.INVOLUNTARY.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "patient_id": patient_id,
            "evaluation_id": evaluation_id,
            "unit_id": unit_id,
            "requested_legal_status": requested_legal_status,
        },
        overrides,
    )


def safety_search_payload(
    search_witness_clinician_id: str,
    search_type: str = SearchType.WANDED.value,
    outcome: str = "COMPLETED",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "search_type": search_type,
            "search_witness_clinician_id": search_witness_clinician_id,
            "search_items_secured_count": 2,
            "contraband_found": False,
            "outcome": outcome,
        },
        overrides,
    )


def placement_payload(
    unit_id: str,
    expected_unit_version: int,
    bed_id: Optional[str] = None,
    posture_override_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "unit_id": unit_id,
        "expected_unit_version": expected_unit_version,
    }
    if bed_id is not None:
        payload["bed_id"] = bed_id
    if posture_override_reason is not None:
        payload["posture_override_reason"] = posture_override_reason
    return _merge(payload, overrides)


def conversion_payload(
    conversion_note: str = "Patient now consents to remain for treatment.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"conversion_note": conversion_note}, overrides)


def discharge_plan_payload(
    follow_up_appointment_at: str,
    follow_up_provider_name: str = "Eastside Community Mental Health",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "follow_up_provider_name": follow_up_provider_name,
            "follow_up_appointment_at": follow_up_appointment_at,
        },
        overrides,
    )


def discharge_payload(
    discharge_summary: str = "Stabilized, safety plan reviewed, medications reconciled.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"discharge_summary": discharge_summary}, overrides)


# ---------------------------------------------------------------------------
# Discharge requests
# ---------------------------------------------------------------------------


def discharge_request_payload(
    admission_id: str,
    requested_by: str = RequestedBy.PATIENT.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"admission_id": admission_id, "requested_by": requested_by}, overrides
    )


def discharge_response_payload(
    decision: str = DischargeDecision.GRANT.value,
    response_note: str = "Reviewed with the treatment team.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"decision": decision, "response_note": response_note}, overrides)


# ---------------------------------------------------------------------------
# Restraint episodes
# ---------------------------------------------------------------------------


def restraint_payload(
    admission_id: str,
    intervention_type: str = InterventionType.MECHANICAL_RESTRAINT.value,
    ordered_duration_minutes: int = 30,
    clinical_justification: str = "Imminent risk of serious self-injury.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "admission_id": admission_id,
            "intervention_type": intervention_type,
            "ordered_duration_minutes": ordered_duration_minutes,
            "clinical_justification": clinical_justification,
        },
        overrides,
    )


def face_to_face_payload(
    assessment_note: str = "Airway, circulation and skin integrity assessed.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"assessment_note": assessment_note}, overrides)


def monitoring_check_payload(
    check_type: str = CheckType.CIRCULATION.value,
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"check_type": check_type}
    if note is not None:
        payload["note"] = note
    return _merge(payload, overrides)


def release_payload(
    release_note: str = "Behaviour settled, restraint discontinued.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"release_note": release_note}, overrides)


def debrief_payload(
    patient_participated_in_debrief: bool = True,
    staff_participants_count: int = 2,
    debrief_note: str = "Triggers and alternatives reviewed with the patient.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "patient_participated_in_debrief": patient_participated_in_debrief,
            "staff_participants_count": staff_participants_count,
            "debrief_note": debrief_note,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Capacity and consent
# ---------------------------------------------------------------------------


def capacity_determination_payload(
    admission_id: str,
    expected_admission_version: int,
    capacity_present: bool = True,
    surrogate_name: Optional[str] = None,
    surrogate_relationship: Optional[str] = None,
    surrogate_authority_scope: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "admission_id": admission_id,
        "expected_admission_version": expected_admission_version,
        "capacity_present": capacity_present,
    }
    if not capacity_present:
        payload["surrogate_name"] = surrogate_name or "Marta Vance"
        payload["surrogate_relationship"] = (
            surrogate_relationship or SurrogateRelationship.GUARDIAN.value
        )
        payload["surrogate_authority_scope"] = (
            surrogate_authority_scope or SurrogateAuthorityScope.FULL.value
        )
    else:
        for key, value in (
            ("surrogate_name", surrogate_name),
            ("surrogate_relationship", surrogate_relationship),
            ("surrogate_authority_scope", surrogate_authority_scope),
        ):
            if value is not None:
                payload[key] = value
    return _merge(payload, overrides)


def medication_consent_payload(
    admission_id: str,
    medication_name: str = "Olanzapine 10 mg",
    consent_basis: str = ConsentBasis.PATIENT_CONSENT.value,
    capacity_determination_id: Optional[str] = None,
    emergency_justification: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "admission_id": admission_id,
        "medication_name": medication_name,
        "consent_basis": consent_basis,
    }
    if capacity_determination_id is not None:
        payload["capacity_determination_id"] = capacity_determination_id
    if emergency_justification is not None:
        payload["emergency_justification"] = emergency_justification
    elif consent_basis == ConsentBasis.EMERGENCY_OVERRIDE.value:
        payload["emergency_justification"] = (
            "Acute agitation with imminent danger; no time to obtain consent."
        )
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"to_iso8601": to_iso8601}, overrides)
