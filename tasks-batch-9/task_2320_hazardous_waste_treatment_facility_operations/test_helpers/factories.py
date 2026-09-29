"""Request payload builders. Every builder returns a valid body and accepts
keyword overrides so a test can vary exactly the field under examination.
"""

from typing import Any, Dict, List, Optional

from .constants import CLOCK_START, TEST_DEFAULTS


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay overrides on base; a value of `None` removes the key entirely."""
    body = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            body.pop(key, None)
        else:
            body[key] = value
    return body


class _Omit:
    """Sentinel meaning "leave this field out of the request body"."""

    def __repr__(self):
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# ─── Clock ────────────────────────────────────────────────────────────────────
def clock_payload(current_utc: str = CLOCK_START) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ─── Facility ─────────────────────────────────────────────────────────────────
def facility_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": TEST_DEFAULTS["facility_name"],
            "epa_id": TEST_DEFAULTS["facility_epa_id"],
            "permit_number": TEST_DEFAULTS["permit_number"],
            "permit_expires_at": TEST_DEFAULTS["permit_expires_at"],
            "permitted_methods": ["INCINERATION", "STABILIZATION", "NEUTRALIZATION"],
            "max_concurrent_treatment_batches": TEST_DEFAULTS[
                "max_concurrent_treatment_batches"
            ],
            "post_closure_cost_cents": TEST_DEFAULTS["post_closure_cost_cents"],
        },
        overrides,
    )


def permit_renewal_payload(
    requested_permit_expires_at: str = "2029-06-30T00:00:00Z", **overrides
) -> Dict[str, Any]:
    return _merge({"requested_permit_expires_at": requested_permit_expires_at}, overrides)


def permit_decision_payload(decision: str = "GRANT", **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {"decision": decision}
    if decision == "GRANT":
        body["new_permit_expires_at"] = "2029-06-30T00:00:00Z"
    return _merge(body, overrides)


# ─── Financial assurance instrument ───────────────────────────────────────────
def instrument_payload(
    facility_id: str,
    expected_facility_version: int,
    face_amount_cents: int = TEST_DEFAULTS["instrument_face_amount_cents"],
    instrument_type: str = "TRUST_FUND",
    effective_on: str = "2026-07-01",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "facility_id": facility_id,
            "instrument_type": instrument_type,
            "face_amount_cents": face_amount_cents,
            "effective_on": effective_on,
            "expected_facility_version": expected_facility_version,
        },
        overrides,
    )


def instrument_cancel_payload(reason_code: str = "SWITCHING_INSTRUMENT", **overrides):
    return _merge({"reason_code": reason_code}, overrides)


# ─── Generator ────────────────────────────────────────────────────────────────
def generator_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "epa_id": TEST_DEFAULTS["generator_epa_id"],
            "name": TEST_DEFAULTS["generator_name"],
            "generator_category": "LQG",
            "state_code": "TX",
        },
        overrides,
    )


def generator_status_payload(to_status: str, reason_code: Optional[str] = None, **overrides):
    body: Dict[str, Any] = {"to_status": to_status}
    if reason_code is not None:
        body["reason_code"] = reason_code
    return _merge(body, overrides)


# ─── Waste profile ────────────────────────────────────────────────────────────
def waste_profile_payload(generator_id: str, facility_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "generator_id": generator_id,
            "facility_id": facility_id,
            "waste_codes": ["D001"],
            "physical_form": "SOLID",
            "compatibility_class": "ORGANIC_SOLVENT",
            "ldr_subcategory": "NONE",
            "declared_constituent_ppm": 12000.0,
            "declared_flash_point_c": 42.0,
            "declared_ph": 7.0,
            "requested_treatment_method": "INCINERATION",
            "recertification_months": 12,
        },
        overrides,
    )


def sample_payload(
    expected_waste_profile_version: int,
    sample_type: str = "FINGERPRINT",
    measured_constituent_ppm: float = 12500.0,
    measured_flash_point_c: float = 43.0,
    measured_ph: float = 7.2,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "sample_type": sample_type,
            "measured_constituent_ppm": measured_constituent_ppm,
            "measured_flash_point_c": measured_flash_point_c,
            "measured_ph": measured_ph,
            "expected_waste_profile_version": expected_waste_profile_version,
        },
        overrides,
    )


def profile_decision_payload(
    decision: str = "APPROVE", approved_treatment_method: str = "INCINERATION", **overrides
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"decision": decision}
    if decision == "APPROVE":
        body["approved_treatment_method"] = approved_treatment_method
    return _merge(body, overrides)


def profile_status_payload(to_status: str, reason_code: Optional[str] = None, **overrides):
    body: Dict[str, Any] = {"to_status": to_status}
    if reason_code is not None:
        body["reason_code"] = reason_code
    return _merge(body, overrides)


# ─── Storage unit ─────────────────────────────────────────────────────────────
def storage_unit_payload(facility_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "facility_id": facility_id,
            "unit_code": "CA-01",
            "unit_type": "CONTAINER_AREA",
            "permitted_capacity_kg": 20000.0,
            "aisle_width_cm": 120.0,
            "aisle_free_container_capacity": 4,
            "inspection_frequency_days": 7,
            "allowed_compatibility_classes": ["ORGANIC_SOLVENT", "ACID"],
            "air_emission_control_level": "LEVEL_2",
            "containment_volume_l": 5000.0,
        },
        overrides,
    )


def tank_unit_payload(facility_id: str, **overrides) -> Dict[str, Any]:
    """A LEVEL_2 tank system: leak definition 250.0 ppm, daily inspection."""
    return storage_unit_payload(
        facility_id,
        unit_code=overrides.pop("unit_code", "TK-01"),
        unit_type="TANK_SYSTEM",
        permitted_capacity_kg=overrides.pop("permitted_capacity_kg", 20000.0),
        aisle_width_cm=overrides.pop("aisle_width_cm", 200.0),
        aisle_free_container_capacity=overrides.pop("aisle_free_container_capacity", 0),
        inspection_frequency_days=overrides.pop("inspection_frequency_days", 1),
        allowed_compatibility_classes=overrides.pop(
            "allowed_compatibility_classes", ["ORGANIC_SOLVENT"]
        ),
        air_emission_control_level=overrides.pop("air_emission_control_level", "LEVEL_2"),
        containment_volume_l=overrides.pop("containment_volume_l", 30000.0),
        **overrides,
    )


def storage_unit_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if to_status == "CLOSING":
        body["closure_plan_ref"] = "CP-CA01-2026"
    return _merge(body, overrides)


# ─── Manifest ─────────────────────────────────────────────────────────────────
def manifest_line_payload(
    waste_profile_id: str,
    declared_quantity_kg: float = 1000.0,
    declared_container_count: int = 4,
    is_bulk: bool = False,
) -> Dict[str, Any]:
    return {
        "waste_profile_id": waste_profile_id,
        "declared_quantity_kg": declared_quantity_kg,
        "declared_container_count": declared_container_count,
        "is_bulk": is_bulk,
    }


def manifest_payload(
    generator_id: str,
    facility_id: str,
    lines: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "generator_id": generator_id,
            "facility_id": facility_id,
            "manifest_tracking_number": TEST_DEFAULTS["manifest_tracking_number"],
            "transporter_epa_id": TEST_DEFAULTS["transporter_epa_id"],
            "shipped_on": TEST_DEFAULTS["shipped_on"],
            "lines": lines if lines is not None else [],
        },
        overrides,
    )


def receipt_line(
    line_number: int, received_quantity_kg: float, received_container_count: int
) -> Dict[str, Any]:
    return {
        "line_number": line_number,
        "received_quantity_kg": received_quantity_kg,
        "received_container_count": received_container_count,
    }


def receive_payload(received_lines: List[Dict[str, Any]], **overrides) -> Dict[str, Any]:
    return _merge({"received_lines": received_lines}, overrides)


def discrepancy_resolution_payload(
    resolution_type: str,
    discrepancy_report_filed: bool = True,
    adjusted_lines: Optional[List[Dict[str, Any]]] = None,
    rejected_line_numbers: Optional[List[int]] = None,
    **overrides,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "resolution_type": resolution_type,
        "discrepancy_report_filed": discrepancy_report_filed,
    }
    if adjusted_lines is not None:
        body["adjusted_lines"] = adjusted_lines
    if rejected_line_numbers is not None:
        body["rejected_line_numbers"] = rejected_line_numbers
    return _merge(body, overrides)


def certify_payload(certifier_note: Optional[str] = None, **overrides) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if certifier_note is not None:
        body["certifier_note"] = certifier_note
    return _merge(body, overrides)


# ─── Container ────────────────────────────────────────────────────────────────
def container_payload(
    manifest_line_id: str,
    storage_unit_id: str,
    net_weight_kg: float = 200.0,
    capacity_kg: float = 250.0,
    label_waste_codes: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "manifest_line_id": manifest_line_id,
            "storage_unit_id": storage_unit_id,
            "container_type": "DRUM_55G",
            "capacity_kg": capacity_kg,
            "net_weight_kg": net_weight_kg,
            "accumulation_start_date": CLOCK_START,
            "label_waste_codes": label_waste_codes or ["D001"],
            "label_hazard_class": "3",
            "label_accumulation_start_marked": True,
        },
        overrides,
    )


def custody_payload(to_custody_state: str, reason_code: Optional[str] = None, **overrides):
    body: Dict[str, Any] = {"to_custody_state": to_custody_state}
    if reason_code is not None:
        body["reason_code"] = reason_code
    return _merge(body, overrides)


def compliance_payload(to_compliance_state: str, finding_code: Optional[str] = None, **overrides):
    body: Dict[str, Any] = {"to_compliance_state": to_compliance_state}
    if finding_code is not None:
        body["finding_code"] = finding_code
    return _merge(body, overrides)


# ─── Treatment batch ──────────────────────────────────────────────────────────
def treatment_batch_payload(
    facility_id: str,
    storage_unit_id: str,
    container_ids: List[str],
    treatment_method: str = "INCINERATION",
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-01T12:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "facility_id": facility_id,
            "storage_unit_id": storage_unit_id,
            "treatment_method": treatment_method,
            "container_ids": container_ids,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def batch_operation_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def complete_batch_payload(
    residue_mass_kg: float,
    residue_constituent_ppm: float,
    residue_flash_point_c: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "action": "COMPLETE",
        "residue_mass_kg": residue_mass_kg,
        "residue_constituent_ppm": residue_constituent_ppm,
    }
    if residue_flash_point_c is not None:
        body["residue_flash_point_c"] = residue_flash_point_c
    return _merge(body, overrides)


def ldr_verification_payload(
    verification_sample_ppm: float, verification_note: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"verification_sample_ppm": verification_sample_ppm}
    if verification_note is not None:
        body["verification_note"] = verification_note
    return _merge(body, overrides)


# ─── Inspections, repair orders, findings ─────────────────────────────────────
def inspection_payload(
    storage_unit_id: str,
    inspection_type: str = "WEEKLY_CONTAINER_AREA",
    finding_code: str = "NONE",
    container_id: Optional[str] = None,
    measured_organic_vapor_ppm: Optional[float] = None,
    measured_aisle_width_cm: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "storage_unit_id": storage_unit_id,
        "inspection_type": inspection_type,
        "finding_code": finding_code,
    }
    if container_id is not None:
        body["container_id"] = container_id
    if measured_organic_vapor_ppm is not None:
        body["measured_organic_vapor_ppm"] = measured_organic_vapor_ppm
    if measured_aisle_width_cm is not None:
        body["measured_aisle_width_cm"] = measured_aisle_width_cm
    return _merge(body, overrides)


def air_monitoring_payload(
    storage_unit_id: str, measured_organic_vapor_ppm: float, **overrides
) -> Dict[str, Any]:
    return inspection_payload(
        storage_unit_id,
        inspection_type="AIR_MONITORING",
        finding_code=overrides.pop("finding_code", "NONE"),
        measured_organic_vapor_ppm=measured_organic_vapor_ppm,
        **overrides,
    )


def repair_action_payload(
    action: str,
    monitored_ppm: Optional[float] = None,
    justification_code: Optional[str] = None,
    delayed_due_at: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"action": action}
    if monitored_ppm is not None:
        body["monitored_ppm"] = monitored_ppm
    if justification_code is not None:
        body["justification_code"] = justification_code
    if delayed_due_at is not None:
        body["delayed_due_at"] = delayed_due_at
    return _merge(body, overrides)


def finding_payload(
    facility_id: str,
    finding_class: str = "SNC",
    citation_code: str = "40CFR264.174",
    corrective_action_due_at: str = "2026-08-31T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "facility_id": facility_id,
            "finding_class": finding_class,
            "citation_code": citation_code,
            "corrective_action_due_at": corrective_action_due_at,
            "is_prior_release": False,
        },
        overrides,
    )


def finding_status_payload(
    to_status: str,
    corrective_action_completed_on: Optional[str] = None,
    reason_code: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if to_status == "RESPONDED":
        body["corrective_action_completed_on"] = corrective_action_completed_on or "2026-08-05"
    elif corrective_action_completed_on is not None:
        body["corrective_action_completed_on"] = corrective_action_completed_on
    if reason_code is not None:
        body["reason_code"] = reason_code
    return _merge(body, overrides)
