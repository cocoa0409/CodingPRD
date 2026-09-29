"""
Request payload factories for the Warewashing API.

Each factory returns a valid payload with canonical field values and lets a
caller override any field with a keyword argument. Passing `field=None` for an
optional field removes it from the payload entirely, which is how a test drives
the "omitted" branch of a defaulted field.

Money is always an integer number of whole cents (§2.6) — never a string and
never a float.
"""

import itertools
from typing import Any, Dict, List, Optional

from . import constants as C
from .types import (
    BASIS_NAMEPLATE,
    CERT_L2,
    CLASS_DOOR_TYPE,
    DECISION_VERIFIED,
    PRODUCT_DETERGENT,
    PRODUCT_SANITIZER,
    REASON_SUSPECTED_THEFT,
    SOURCE_DEVICE,
    SYMPTOM_RACK_QUALITY,
    TECH_AVAILABLE,
)

_OMIT = object()

_seq = itertools.count(1)


def next_suffix() -> int:
    """Monotone counter for building unique codes inside one test process."""
    return next(_seq)


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the private omission sentinel."""
    return {k: v for k, v in payload.items() if v is not _OMIT}


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of None removes the key from the payload."""
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── §3.1 Customers ────────────────────────────────────────────────────


def customer_payload(**overrides) -> Dict[str, Any]:
    """A valid customer registration payload."""
    payload = {
        "name": f"Harbour Point Catering {next_suffix()}",
        "sustainability_goal_water_l": C.CUSTOMER_SUSTAINABILITY_GOAL_WATER_L,
    }
    return _apply(payload, overrides)


def credit_hold_customer_payload(**overrides) -> Dict[str, Any]:
    """A customer seeded straight onto CREDIT_HOLD billing."""
    payload = customer_payload()
    payload["billing_status"] = "CREDIT_HOLD"
    return _apply(payload, overrides)


# ─── §3.1 Sites ────────────────────────────────────────────────────────


def site_payload(customer_id: str, **overrides) -> Dict[str, Any]:
    """A valid kitchen registration payload with canonical tariffs."""
    payload = {
        "customer_id": customer_id,
        "name": f"Harbour Point Galley {next_suffix()}",
        "region_code": C.SITE_REGION_CODE,
        "operating_window_start_minute_utc": C.SITE_OPERATING_WINDOW_START_MINUTE,
        "operating_window_end_minute_utc": C.SITE_OPERATING_WINDOW_END_MINUTE,
        "baseline_water_l_per_rack": C.SITE_BASELINE_WATER_L_PER_RACK,
        "baseline_kwh_per_rack": C.SITE_BASELINE_KWH_PER_RACK,
        "water_cost_cents_per_1000l": C.SITE_WATER_COST_CENTS_PER_1000L,
        "energy_cost_cents_per_kwh": C.SITE_ENERGY_COST_CENTS_PER_KWH,
    }
    return _apply(payload, overrides)


# ─── §3.1 Chemical catalog ─────────────────────────────────────────────


def detergent_payload(**overrides) -> Dict[str, Any]:
    """DET-100: the canonical detergent. Sanitizer fields are omitted."""
    payload = {
        "sku": "DET-100",
        "product_type": PRODUCT_DETERGENT,
        "concentration_target_ppm": C.DET_CONCENTRATION_TARGET_PPM,
        "spec_dose_ml_per_rack": C.DET_SPEC_DOSE_ML_PER_RACK,
        "unit_size_ml": C.DET_UNIT_SIZE_ML,
        "unit_price_cents": C.DET_UNIT_PRICE_CENTS,
    }
    return _apply(payload, overrides)


def rinse_aid_payload(**overrides) -> Dict[str, Any]:
    """RIN-050: a rinse aid. Sanitizer fields are omitted."""
    payload = {
        "sku": "RIN-050",
        "product_type": "RINSE_AID",
        "concentration_target_ppm": 300,
        "spec_dose_ml_per_rack": 1.50,
        "unit_size_ml": 10000,
        "unit_price_cents": 5400,
    }
    return _apply(payload, overrides)


def sanitizer_payload(**overrides) -> Dict[str, Any]:
    """SAN-200: the canonical sanitizer, with all three sanitizer fields."""
    payload = {
        "sku": "SAN-200",
        "product_type": PRODUCT_SANITIZER,
        "concentration_target_ppm": C.SAN_CONCENTRATION_TARGET_PPM,
        "spec_dose_ml_per_rack": C.SAN_SPEC_DOSE_ML_PER_RACK,
        "unit_size_ml": C.SAN_UNIT_SIZE_ML,
        "unit_price_cents": C.SAN_UNIT_PRICE_CENTS,
        "sanitizer_min_ppm": C.SAN_MIN_PPM,
        "sanitizer_max_ppm": C.SAN_MAX_PPM,
        "min_contact_seconds": C.SAN_MIN_CONTACT_SECONDS,
    }
    return _apply(payload, overrides)


# ─── §3.1 Machine catalog ──────────────────────────────────────────────


def machine_model_payload(**overrides) -> Dict[str, Any]:
    """DT-88: the canonical door-type machine model."""
    payload = {
        "model_code": "DT-88",
        "machine_class": CLASS_DOOR_TYPE,
        "racks_per_hour": C.DT88_RACKS_PER_HOUR,
        "rated_water_l_per_rack": C.DT88_RATED_WATER_L_PER_RACK,
        "rated_kwh_per_rack": C.DT88_RATED_KWH_PER_RACK,
        "min_final_rinse_temp_f": C.DT88_MIN_FINAL_RINSE_TEMP_F,
        "min_wash_temp_f": C.DT88_MIN_WASH_TEMP_F,
        "min_rinse_pressure_psi": C.DT88_MIN_RINSE_PRESSURE_PSI,
        "max_rinse_pressure_psi": C.DT88_MAX_RINSE_PRESSURE_PSI,
        "equipment_value_cents": C.DT88_EQUIPMENT_VALUE_CENTS,
        "max_cycles_between_calibrations": C.DT88_MAX_CYCLES_BETWEEN_CALIBRATIONS,
    }
    return _apply(payload, overrides)


# ─── §3.1 Technicians ──────────────────────────────────────────────────


def technician_payload(**overrides) -> Dict[str, Any]:
    """A canonical NW L2 technician, AVAILABLE for dispatch."""
    payload = {
        "name": f"Dana Okonjo {next_suffix()}",
        "region_code": C.SITE_REGION_CODE,
        "certification_level": CERT_L2,
        "status": TECH_AVAILABLE,
    }
    return _apply(payload, overrides)


# ─── §3.2 Service agreements ───────────────────────────────────────────


def service_agreement_payload(
    customer_id: str, covered_product_ids: List[str], **overrides
) -> Dict[str, Any]:
    """A valid agreement draft. The request never carries term_end_date."""
    payload = {
        "customer_id": customer_id,
        "agreement_code": f"AGR-2701-{next_suffix()}",
        "start_date": "2026-08-01",
        "minimum_term_months": C.AGREEMENT_MIN_TERM_MONTHS,
        "monthly_minimum_spend_cents": C.AGREEMENT_MONTHLY_MINIMUM_SPEND_CENTS,
        "covered_product_ids": list(covered_product_ids),
    }
    return _apply(payload, overrides)


def terminate_payload(effective_date: str = "2026-08-01", **overrides):
    """Termination always carries effective_date."""
    payload = {"effective_date": effective_date}
    return _apply(payload, overrides)


def renewal_payload(renewal_term_months: Optional[int] = None, **overrides):
    """Renewal accepts one optional field, renewal_term_months."""
    payload: Dict[str, Any] = {}
    if renewal_term_months is not None:
        payload["renewal_term_months"] = renewal_term_months
    return _apply(payload, overrides)


# ─── §3.3 Machine placements ───────────────────────────────────────────


def machine_placement_payload(
    site_id: str,
    agreement_id: str,
    machine_model_id: str,
    expected_agreement_version: int,
    asset_tag: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """A valid placement create, carrying the mandatory agreement version token."""
    payload = {
        "site_id": site_id,
        "agreement_id": agreement_id,
        "machine_model_id": machine_model_id,
        "asset_tag": asset_tag or f"AT-{next_suffix():04d}",
        "expected_agreement_version": expected_agreement_version,
    }
    return _apply(payload, overrides)


def retrieval_order_payload(retrieval_due_date: Optional[str] = None, **overrides):
    """A retrieval order, optionally supplying retrieval_due_date."""
    payload: Dict[str, Any] = {}
    if retrieval_due_date is not None:
        payload["retrieval_due_date"] = retrieval_due_date
    return _apply(payload, overrides)


# ─── §3.4 Dispensers and telemetry ─────────────────────────────────────


def dispenser_payload(
    placement_id: str,
    product_id: str,
    calibrated_dose_ml_per_rack: float = C.DET_SPEC_DOSE_ML_PER_RACK,
    **overrides,
) -> Dict[str, Any]:
    """A valid dispenser fitting payload."""
    payload = {
        "placement_id": placement_id,
        "product_id": product_id,
        "calibrated_dose_ml_per_rack": calibrated_dose_ml_per_rack,
    }
    return _apply(payload, overrides)


def telemetry_reading_payload(
    reading_at: str,
    cycle_count_total: int,
    wash_temp_f: int = 160,
    final_rinse_temp_f: int = 185,
    rinse_pressure_psi: int = 20,
    source: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """
    A healthy DEVICE reading against DT-88 thresholds: wash 160 >= 150,
    final rinse 185 >= 180, pressure 20 inside [15, 25].
    """
    payload: Dict[str, Any] = {
        "reading_at": reading_at,
        "cycle_count_total": cycle_count_total,
        "wash_temp_f": wash_temp_f,
        "final_rinse_temp_f": final_rinse_temp_f,
        "rinse_pressure_psi": rinse_pressure_psi,
    }
    if source is not None:
        payload["source"] = source
    return _apply(payload, overrides)


def device_reading_payload(reading_at: str, cycle_count_total: int, **overrides):
    """A healthy reading with source explicitly DEVICE."""
    return telemetry_reading_payload(
        reading_at, cycle_count_total, source=SOURCE_DEVICE, **overrides
    )


def manual_audit_reading_payload(reading_at: str, cycle_count_total: int, **overrides):
    """A MANUAL_AUDIT reading: opens no alert and contributes no racks."""
    return telemetry_reading_payload(
        reading_at, cycle_count_total, source="MANUAL_AUDIT", **overrides
    )


# ─── §3.5 Service tickets ──────────────────────────────────────────────


def service_ticket_payload(
    placement_id: str, reported_symptom: str = SYMPTOM_RACK_QUALITY, **overrides
) -> Dict[str, Any]:
    """A customer-reported ticket; reported_symptom is mandatory on this route."""
    payload = {"placement_id": placement_id, "reported_symptom": reported_symptom}
    return _apply(payload, overrides)


def dispatch_payload(override_technician_id: Optional[str] = None, **overrides):
    """A dispatch request, optionally naming an override technician."""
    payload: Dict[str, Any] = {}
    if override_technician_id is not None:
        payload["override_technician_id"] = override_technician_id
    return _apply(payload, overrides)


# ─── §3.6 Service visits and calibration records ───────────────────────


def service_visit_payload(
    ticket_id: str,
    technician_id: str,
    scheduled_start_at: str = "2026-08-01T10:00:00Z",
    scheduled_end_at: str = "2026-08-01T11:00:00Z",
    follow_up_to_visit_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """A visit booking with a one-hour window."""
    payload: Dict[str, Any] = {
        "ticket_id": ticket_id,
        "technician_id": technician_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    if follow_up_to_visit_id is not None:
        payload["follow_up_to_visit_id"] = follow_up_to_visit_id
    return _apply(payload, overrides)


def calibration_record_payload(
    dispenser_id: str,
    measured_ppm: int,
    measured_dose_ml_per_rack: float,
    expected_dispenser_version: int,
    adjusted_dose_ml_per_rack: Optional[float] = None,
    contact_seconds: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """
    A calibration record carrying the mandatory dispenser version token.
    `adjusted_dose_ml_per_rack` and `contact_seconds` are optional in the payload.
    """
    payload: Dict[str, Any] = {
        "dispenser_id": dispenser_id,
        "measured_ppm": measured_ppm,
        "measured_dose_ml_per_rack": measured_dose_ml_per_rack,
        "expected_dispenser_version": expected_dispenser_version,
    }
    if adjusted_dose_ml_per_rack is not None:
        payload["adjusted_dose_ml_per_rack"] = adjusted_dose_ml_per_rack
    if contact_seconds is not None:
        payload["contact_seconds"] = contact_seconds
    return _apply(payload, overrides)


def submit_visit_payload(repair_confirmed: Optional[bool] = None, **overrides):
    """Submission accepts one optional field, repair_confirmed."""
    payload: Dict[str, Any] = {}
    if repair_confirmed is not None:
        payload["repair_confirmed"] = repair_confirmed
    return _apply(payload, overrides)


def verify_visit_payload(
    decision: str = DECISION_VERIFIED,
    rejection_reason: Optional[str] = None,
    **overrides,
):
    """Adjudication carries decision, plus rejection_reason when REJECTED."""
    payload: Dict[str, Any] = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return _apply(payload, overrides)


# ─── §3.7 Deliveries and variance reviews ──────────────────────────────


def chemical_delivery_payload(
    site_id: str,
    product_id: str,
    expected_site_version: int,
    unit_count: int = 1,
    delivered_at: str = "2026-08-05T12:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """A delivery carrying the mandatory site version token."""
    payload = {
        "site_id": site_id,
        "product_id": product_id,
        "delivered_at": delivered_at,
        "unit_count": unit_count,
        "expected_site_version": expected_site_version,
    }
    return _apply(payload, overrides)


def usage_variance_review_payload(
    site_id: str,
    product_id: str,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
    basis: str = BASIS_NAMEPLATE,
    opening_inventory_ml: int = 5000,
    ending_inventory_ml: int = 5000,
    **overrides,
) -> Dict[str, Any]:
    """A DRAFT variance review over a half-open window."""
    payload = {
        "site_id": site_id,
        "product_id": product_id,
        "period_start": period_start,
        "period_end": period_end,
        "basis": basis,
        "opening_inventory_ml": opening_inventory_ml,
        "ending_inventory_ml": ending_inventory_ml,
    }
    return _apply(payload, overrides)


# ─── §3.8 Investigation cases ──────────────────────────────────────────


def investigation_case_payload(
    variance_review_id: str, opened_reason: str = REASON_SUSPECTED_THEFT, **overrides
) -> Dict[str, Any]:
    """Opening a case against a PUBLISHED review."""
    payload = {
        "variance_review_id": variance_review_id,
        "opened_reason": opened_reason,
    }
    return _apply(payload, overrides)


def submit_for_review_payload(evidence_types: List[str], **overrides):
    """Evidence submission carries a non-empty evidence_types array."""
    payload = {"evidence_types": list(evidence_types)}
    return _apply(payload, overrides)


def case_review_payload(
    decision: str,
    remediation: Optional[str] = None,
    finding_note: Optional[str] = None,
    **overrides,
):
    """Case adjudication: decision plus optional remediation and finding_note."""
    payload: Dict[str, Any] = {"decision": decision}
    if remediation is not None:
        payload["remediation"] = remediation
    if finding_note is not None:
        payload["finding_note"] = finding_note
    return _apply(payload, overrides)


# ─── §2.4 Clock ────────────────────────────────────────────────────────


def clock_payload(current_utc: str, **overrides) -> Dict[str, Any]:
    """A clock advance to the given instant."""
    payload = {"current_utc": current_utc}
    return _apply(payload, overrides)


# ─── §3.9 Report query params ──────────────────────────────────────────


def report_params(
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
    basis: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Query parameters for the two computed reads of §3.9."""
    params: Dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
    }
    if basis is not None:
        params["basis"] = basis
    return _apply(params, overrides)
