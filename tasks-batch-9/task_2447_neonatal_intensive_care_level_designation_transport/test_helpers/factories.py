"""Request-payload builders.

Each builder returns only the fields a caller is allowed to supply for that
endpoint — never a derived or server-owned field. Overrides are applied last, so
a test can pass an explicit value or an intentionally malformed one.
"""

from typing import Any, Dict, List, Optional

from .constants import CLOCK_START

# ---------------------------------------------------------------------------
# Operational
# ---------------------------------------------------------------------------


def clock_payload(current_utc: str = CLOCK_START, **overrides: Any) -> Dict[str, Any]:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


def capacity_sweep_payload(unit_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if unit_id is not None:
        payload["unit_id"] = unit_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# NicuUnit
# ---------------------------------------------------------------------------


def nicu_unit_payload(
    name: str = "Regional NICU A",
    hospital_type: str = "REGIONAL_CENTER",
    staffed_bed_target: int = 4,
    designated_level: str = "LEVEL_III",
    transport_capable: bool = True,
    annual_admission_volume: int = 400,
    followup_clinic_daily_capacity: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "hospital_type": hospital_type,
        "staffed_bed_target": staffed_bed_target,
        "designated_level": designated_level,
        "transport_capable": transport_capable,
        "annual_admission_volume": annual_admission_volume,
        "followup_clinic_daily_capacity": followup_clinic_daily_capacity,
    }
    payload.update(overrides)
    return payload


def community_unit_payload(
    name: str = "Community Hospital B",
    staffed_bed_target: int = 6,
    designated_level: str = "LEVEL_I",
    transport_capable: bool = False,
    annual_admission_volume: int = 300,
    followup_clinic_daily_capacity: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    return nicu_unit_payload(
        name=name,
        hospital_type="COMMUNITY",
        staffed_bed_target=staffed_bed_target,
        designated_level=designated_level,
        transport_capable=transport_capable,
        annual_admission_volume=annual_admission_volume,
        followup_clinic_daily_capacity=followup_clinic_daily_capacity,
        **overrides,
    )


def unit_patch_payload(expected_unit_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_unit_version": expected_unit_version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DesignationStandard
# ---------------------------------------------------------------------------

STANDARD_PAYLOADS: Dict[str, Dict[str, Any]] = {
    "LEVEL_I": {
        "level": "LEVEL_I",
        "required_credential_codes": [],
        "required_equipment_codes": [],
        "nurse_patient_ratio_denominator": 4.0,
        "min_annual_volume": 100,
        "transport_capability_required": False,
        "min_compliance_score": 85.00,
        "conditional_floor_score": 70.00,
    },
    "LEVEL_II": {
        "level": "LEVEL_II",
        "required_credential_codes": ["RN_NICU_CORE"],
        "required_equipment_codes": ["CONVENTIONAL_VENT"],
        "nurse_patient_ratio_denominator": 3.0,
        "min_annual_volume": 300,
        "transport_capability_required": False,
        "min_compliance_score": 85.00,
        "conditional_floor_score": 70.00,
    },
    "LEVEL_III": {
        "level": "LEVEL_III",
        "required_credential_codes": ["NEO_BOARD", "RN_NICU_CORE"],
        "required_equipment_codes": ["CONVENTIONAL_VENT", "HFOV"],
        "nurse_patient_ratio_denominator": 2.0,
        "min_annual_volume": 500,
        "transport_capability_required": False,
        "min_compliance_score": 85.00,
        "conditional_floor_score": 70.00,
    },
    "LEVEL_IV": {
        "level": "LEVEL_IV",
        "required_credential_codes": ["NEO_BOARD", "NNP", "RN_NICU_CORE", "RT_NEO"],
        "required_equipment_codes": ["CONVENTIONAL_VENT", "HFOV", "INHALED_NO"],
        "nurse_patient_ratio_denominator": 1.0,
        "min_annual_volume": 500,
        "transport_capability_required": True,
        "min_compliance_score": 90.00,
        "conditional_floor_score": 75.00,
    },
}


def designation_standard_payload(level: str = "LEVEL_III", **overrides: Any) -> Dict[str, Any]:
    payload = dict(STANDARD_PAYLOADS[level])
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# StaffCredential / EquipmentAsset
# ---------------------------------------------------------------------------


def staff_credential_payload(
    unit_id: str,
    credential_code: str = "RN_NICU_CORE",
    holder_reference: str = "rn-pool",
    fte: float = 3.0,
    expires_on: str = "2027-01-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "unit_id": unit_id,
        "credential_code": credential_code,
        "holder_reference": holder_reference,
        "fte": fte,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return payload


def equipment_asset_payload(
    unit_id: str,
    equipment_code: str = "CONVENTIONAL_VENT",
    asset_tag: str = "VENT-1",
    last_service_at: str = "2026-07-01T00:00:00Z",
    service_interval_days: int = 365,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "unit_id": unit_id,
        "equipment_code": equipment_code,
        "asset_tag": asset_tag,
        "last_service_at": last_service_at,
        "service_interval_days": service_interval_days,
    }
    payload.update(overrides)
    return payload


def service_payload(serviced_at: str = CLOCK_START, **overrides: Any) -> Dict[str, Any]:
    payload = {"serviced_at": serviced_at}
    payload.update(overrides)
    return payload


def out_of_service_payload(reason: str = "BIOMED_FAULT", **overrides: Any) -> Dict[str, Any]:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DesignationReview
# ---------------------------------------------------------------------------


def designation_review_payload(
    unit_id: str,
    requested_level: str = "LEVEL_III",
    assigned_nurse_count: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "unit_id": unit_id,
        "requested_level": requested_level,
        "assigned_nurse_count": assigned_nurse_count,
    }
    payload.update(overrides)
    return payload


def review_return_payload(
    return_reason: str = "Credential evidence incomplete", **overrides: Any
) -> Dict[str, Any]:
    payload = {"return_reason": return_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Referral
# ---------------------------------------------------------------------------


def referral_payload(
    referring_unit_id: str,
    receiving_unit_id: str,
    case_reference: str = "CASE-N1",
    referral_kind: str = "INBOUND_NEONATAL",
    gestational_age_weeks: float = 29.0,
    birth_weight_grams: int = 1200,
    support_modality: str = "ROOM_AIR",
    diagnoses: Optional[List[str]] = None,
    planned_surgery: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "referring_unit_id": referring_unit_id,
        "receiving_unit_id": receiving_unit_id,
        "referral_kind": referral_kind,
        "case_reference": case_reference,
        "gestational_age_weeks": gestational_age_weeks,
        "birth_weight_grams": birth_weight_grams,
        "support_modality": support_modality,
        "diagnoses": [] if diagnoses is None else diagnoses,
        "planned_surgery": planned_surgery,
    }
    payload.update(overrides)
    return payload


def request_info_payload(
    requested_items: str = "Latest blood gas and chest film", **overrides: Any
) -> Dict[str, Any]:
    payload = {"requested_items": requested_items}
    payload.update(overrides)
    return payload


def provide_info_payload(**fields: Any) -> Dict[str, Any]:
    return dict(fields)


def accept_referral_payload(expected_unit_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {"expected_unit_version": expected_unit_version}
    payload.update(overrides)
    return payload


def decline_referral_payload(
    decision_reason: str = "CLINICAL_DECLINE", **overrides: Any
) -> Dict[str, Any]:
    payload = {"decision_reason": decision_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TransportRun
# ---------------------------------------------------------------------------


def transport_run_payload(
    reservation_id: str,
    isolette_asset_id: str,
    mode: str = "GROUND",
    crew_composition: Optional[List[str]] = None,
    depart_at: str = "2026-08-01T01:00:00Z",
    planned_return_at: str = "2026-08-01T05:00:00Z",
    weather_minimums_met: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "reservation_id": reservation_id,
        "isolette_asset_id": isolette_asset_id,
        "mode": mode,
        "crew_composition": (
            ["TRANSPORT_RN", "TRANSPORT_RT"] if crew_composition is None else crew_composition
        ),
        "depart_at": depart_at,
        "planned_return_at": planned_return_at,
        "weather_minimums_met": weather_minimums_met,
    }
    payload.update(overrides)
    return payload


def stabilize_payload(
    temp_c: float = 36.5,
    glucose_mg_dl: float = 45,
    mean_bp_mmhg: float = 30,
    spo2_pct: float = 90,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "temp_c": temp_c,
        "glucose_mg_dl": glucose_mg_dl,
        "mean_bp_mmhg": mean_bp_mmhg,
        "spo2_pct": spo2_pct,
    }
    payload.update(overrides)
    return payload


def arrive_payload(arrived_at: str = "2026-08-01T04:00:00Z", **overrides: Any) -> Dict[str, Any]:
    payload = {"arrived_at": arrived_at}
    payload.update(overrides)
    return payload


def abort_payload(abort_reason: str = "WEATHER", **overrides: Any) -> Dict[str, Any]:
    payload = {"abort_reason": abort_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------


def admission_payload(referral_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"referral_id": referral_id}
    payload.update(overrides)
    return payload


def care_update_payload(
    current_weight_grams: int = 1250,
    support_modality: str = "ROOM_AIR",
    central_line_present: bool = False,
    ventilated: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "current_weight_grams": current_weight_grams,
        "support_modality": support_modality,
        "central_line_present": central_line_present,
        "ventilated": ventilated,
    }
    payload.update(overrides)
    return payload


def developmental_round_payload(
    kangaroo_care_minutes: int = 60,
    family_presence_minutes: int = 240,
    cluster_care_compliant: bool = True,
    light_cycling_compliant: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "kangaroo_care_minutes": kangaroo_care_minutes,
        "family_presence_minutes": family_presence_minutes,
        "cluster_care_compliant": cluster_care_compliant,
        "light_cycling_compliant": light_cycling_compliant,
    }
    payload.update(overrides)
    return payload


def infection_event_payload(event: str = "SUSPECT", **overrides: Any) -> Dict[str, Any]:
    payload = {"event": event}
    payload.update(overrides)
    return payload


def back_transfer_ready_payload(
    back_transfer_attestation_note: str = "Feeding and growing, stable in room air",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"back_transfer_attestation_note": back_transfer_attestation_note}
    payload.update(overrides)
    return payload


def back_transfer_referral_payload(
    expected_admission_version: int,
    receiving_unit_id: str,
    case_reference: str = "CASE-BT1",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "expected_admission_version": expected_admission_version,
        "receiving_unit_id": receiving_unit_id,
        "case_reference": case_reference,
    }
    payload.update(overrides)
    return payload


def discharge_payload(disposition: str = "HOME", **overrides: Any) -> Dict[str, Any]:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# MilkBatch
# ---------------------------------------------------------------------------


def milk_batch_payload(
    admission_id: str,
    donor_type: str = "MOTHERS_OWN",
    volume_ml: float = 120.0,
    expressed_at: str = CLOCK_START,
    label_code: str = "LBL-1",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "admission_id": admission_id,
        "donor_type": donor_type,
        "volume_ml": volume_ml,
        "expressed_at": expressed_at,
        "label_code": label_code,
    }
    payload.update(overrides)
    return payload


def verify_milk_payload(label_code: str = "LBL-1", **overrides: Any) -> Dict[str, Any]:
    payload = {"label_code": label_code}
    payload.update(overrides)
    return payload


def milk_volume_payload(volume_ml: float = 30.0, **overrides: Any) -> Dict[str, Any]:
    payload = {"volume_ml": volume_ml}
    payload.update(overrides)
    return payload


def discard_milk_payload(reason: str = "FAMILY_REQUEST", **overrides: Any) -> Dict[str, Any]:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SurgeEscalation
# ---------------------------------------------------------------------------


def surge_escalation_payload(
    unit_id: str,
    requested_beds: int = 6,
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_to: str = "2026-08-02T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "unit_id": unit_id,
        "requested_beds": requested_beds,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


def deny_surge_payload(
    denial_reason: str = "Network capacity retained elsewhere", **overrides: Any
) -> Dict[str, Any]:
    payload = {"denial_reason": denial_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SurveillanceReport
# ---------------------------------------------------------------------------


def surveillance_report_payload(
    unit_id: str,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-08-31T00:00:00Z",
    reported_patient_days: int = 500,
    reported_central_line_days: int = 120,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "unit_id": unit_id,
        "period_start": period_start,
        "period_end": period_end,
        "reported_patient_days": reported_patient_days,
        "reported_central_line_days": reported_central_line_days,
    }
    payload.update(overrides)
    return payload


def submit_report_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def reject_report_payload(
    rejection_reason: str = "Denominator inconsistent with census", **overrides: Any
) -> Dict[str, Any]:
    payload = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# FollowUpEnrollment
# ---------------------------------------------------------------------------


def follow_up_enrollment_payload(
    admission_id: str,
    clinic_unit_id: str,
    target_appointment_date: str = "2026-08-20T09:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "admission_id": admission_id,
        "clinic_unit_id": clinic_unit_id,
        "target_appointment_date": target_appointment_date,
    }
    payload.update(overrides)
    return payload


def schedule_payload(
    confirmed_appointment_date: str = "2026-08-20T09:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    payload = {"confirmed_appointment_date": confirmed_appointment_date}
    payload.update(overrides)
    return payload


def attendance_payload(attended: bool = True, **overrides: Any) -> Dict[str, Any]:
    payload = {"attended": attended}
    payload.update(overrides)
    return payload
