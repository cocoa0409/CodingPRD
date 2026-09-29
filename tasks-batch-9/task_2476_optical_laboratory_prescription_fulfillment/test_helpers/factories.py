"""Payload builders. Every factory accepts ``**overrides``."""

from typing import Any, Dict

from .constants import CLOCK_START, TEST_DEFAULTS

# --------------------------------------------------------------------------
# Canonical reference data used by the two standing scenarios
# --------------------------------------------------------------------------

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "prescriber": {
        "npi": TEST_DEFAULTS["npi_primary"],
        "full_name": TEST_DEFAULTS["prescriber_name"],
        "license_state": TEST_DEFAULTS["license_state"],
        "max_rx_validity_months": 12,
    },
    "insurance_plan": {
        "plan_code": "VSP-PREMIER",
        "frame_allowance_cents": 15000,
        "lens_base_allowance_cents": 9000,
        "coating_allowance_cents": 8000,
        "progressive_copay_cents": 3000,
        "coinsurance_pct": 0.33,
        "annual_benefit_cap_cents": 40000,
        "expedite_covered": False,
        "specialty_requires_prior_auth": True,
    },
    "basic_plan": {
        "plan_code": "VSP-BASIC",
        "frame_allowance_cents": 5000,
        "lens_base_allowance_cents": 9000,
        "coating_allowance_cents": 8000,
        "progressive_copay_cents": 3000,
        "coinsurance_pct": 0.00,
        "annual_benefit_cap_cents": 100000,
        "expedite_covered": False,
        "specialty_requires_prior_auth": True,
    },
    "self_pay_patient": {
        "full_name": TEST_DEFAULTS["self_pay_patient_name"],
        "date_of_birth": TEST_DEFAULTS["self_pay_patient_dob"],
    },
    "insured_patient": {
        "full_name": TEST_DEFAULTS["insured_patient_name"],
        "date_of_birth": TEST_DEFAULTS["insured_patient_dob"],
        "member_number": TEST_DEFAULTS["member_number"],
        "benefit_period_start": "2026-01-01",
    },
    "sv_design": {
        "design_code": "SV-POLY",
        "design_type": "SINGLE_VISION",
        "material": "POLYCARBONATE",
        "allowed_coatings": ["AR_STANDARD", "HARDCOAT"],
        "retail_price_cents": 11995,
        "min_fitting_height_mm": 14.0,
        "min_blank_diameter_mm": 65.0,
        "product_tier": "STANDARD",
        "stock_sku_available": True,
        "base_curve": 6.0,
    },
    "progressive_design": {
        "design_code": "PRG-HI167",
        "design_type": "PROGRESSIVE",
        "material": "HIGH_INDEX_167",
        "allowed_coatings": ["AR_PREMIUM", "HARDCOAT"],
        "retail_price_cents": 31995,
        "min_fitting_height_mm": 18.0,
        "min_blank_diameter_mm": 70.0,
        "product_tier": "PREMIUM",
        "stock_sku_available": False,
        "base_curve": 4.0,
    },
    "sv_tolerance_standard": {
        "design_type": "SINGLE_VISION",
        "power_band_min_abs": 0.0,
        "power_band_max_abs": 6.0,
        "sphere_tolerance_diopters": 0.13,
        "cylinder_tolerance_diopters": 0.13,
        "axis_tolerance_degrees": 3,
        "prism_tolerance_pd": 0.33,
        "allowed_cosmetic_defect_codes": ["MINOR_EDGE_CHIP"],
        "effective_from": "2026-01-01",
    },
    "progressive_tolerance_standard": {
        "design_type": "PROGRESSIVE",
        "power_band_min_abs": 0.0,
        "power_band_max_abs": 6.0,
        "sphere_tolerance_diopters": 0.13,
        "cylinder_tolerance_diopters": 0.13,
        "axis_tolerance_degrees": 3,
        "prism_tolerance_pd": 0.33,
        "allowed_cosmetic_defect_codes": [],
        "effective_from": "2026-01-01",
    },
}


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------


def create_clock_payload(**overrides) -> dict:
    payload = {"current_utc": CLOCK_START}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Registry and catalogue
# --------------------------------------------------------------------------


def create_prescriber_payload(**overrides) -> dict:
    payload = dict(DEFAULTS["prescriber"])
    payload.update(overrides)
    return payload


def create_insurance_plan_payload(**overrides) -> dict:
    payload = dict(DEFAULTS["insurance_plan"])
    payload.update(overrides)
    return payload


def create_basic_plan_payload(**overrides) -> dict:
    payload = dict(DEFAULTS["basic_plan"])
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    """A self-pay patient: a null ``insurance_plan_id`` means self-pay."""
    payload = dict(DEFAULTS["self_pay_patient"])
    payload.update(overrides)
    return payload


def create_insured_patient_payload(insurance_plan_id: str, **overrides) -> dict:
    payload = dict(DEFAULTS["insured_patient"])
    payload["insurance_plan_id"] = insurance_plan_id
    payload.update(overrides)
    return payload


def create_lens_design_payload(**overrides) -> dict:
    payload = dict(DEFAULTS["sv_design"])
    payload.update(overrides)
    return payload


def create_progressive_design_payload(**overrides) -> dict:
    payload = dict(DEFAULTS["progressive_design"])
    payload.update(overrides)
    return payload


def create_tolerance_standard_payload(**overrides) -> dict:
    payload = dict(DEFAULTS["sv_tolerance_standard"])
    payload.update(overrides)
    return payload


def create_progressive_tolerance_standard_payload(**overrides) -> dict:
    payload = dict(DEFAULTS["progressive_tolerance_standard"])
    payload.update(overrides)
    return payload


def create_lens_blank_lot_payload(lens_design_id: str, **overrides) -> dict:
    payload = {
        "lens_design_id": lens_design_id,
        "blank_sku": "BLK-167-80",
        "diameter_mm": 80.0,
        "received_qty": 2,
        "received_on": "2026-06-15",
    }
    payload.update(overrides)
    return payload


def create_lab_machine_payload(**overrides) -> dict:
    payload = {
        "machine_code": "GEN-1",
        "machine_type": "GENERATOR",
        "calibration_buffer_minutes": 15,
    }
    payload.update(overrides)
    return payload


def create_finishing_bay_payload(**overrides) -> dict:
    payload = {"bay_code": "BAY-1", "concurrent_capacity": 2}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Prescriptions
# --------------------------------------------------------------------------


def create_prescription_payload(
    patient_id: str, prescriber_id: str, **overrides
) -> dict:
    """The stock single-vision prescription: -2.00/-1.00 x 90 both eyes."""
    payload = {
        "patient_id": patient_id,
        "prescriber_id": prescriber_id,
        "prescriber_npi_claimed": TEST_DEFAULTS["npi_primary"],
        "prescriber_license_state_claimed": TEST_DEFAULTS["license_state"],
        "sphere_od": -2.0,
        "cylinder_od": -1.0,
        "axis_od": 90,
        "sphere_os": -2.0,
        "cylinder_os": -1.0,
        "axis_os": 90,
        "pd_distance_mm": 63.0,
        "issued_on": TEST_DEFAULTS["issued_on"],
    }
    payload.update(overrides)
    return payload


def create_multifocal_prescription_payload(
    patient_id: str, prescriber_id: str, **overrides
) -> dict:
    """The progressive prescription carrying an add power and a prism."""
    payload = {
        "patient_id": patient_id,
        "prescriber_id": prescriber_id,
        "prescriber_npi_claimed": TEST_DEFAULTS["npi_primary"],
        "prescriber_license_state_claimed": TEST_DEFAULTS["license_state"],
        "sphere_od": -3.0,
        "cylinder_od": -1.25,
        "axis_od": 90,
        "sphere_os": -2.75,
        "cylinder_os": -1.0,
        "axis_os": 85,
        "add_power": 2.0,
        "prism_od": 0.5,
        "prism_os": 0.0,
        "pd_distance_mm": 61.0,
        "issued_on": TEST_DEFAULTS["issued_on"],
    }
    payload.update(overrides)
    return payload


def create_verification_payload(**overrides) -> dict:
    payload = {"verification_note": TEST_DEFAULTS["verification_note"]}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Orders, layouts, jobs, occupations
# --------------------------------------------------------------------------


def create_rx_order_payload(
    patient_id: str, prescription_id: str, lens_design_id: str, **overrides
) -> dict:
    """The stock self-pay order: frame 8995 plus AR_STANDARD."""
    payload = {
        "patient_id": patient_id,
        "prescription_id": prescription_id,
        "lens_design_id": lens_design_id,
        "frame_sku": "FRM-S10",
        "frame_retail_cents": 8995,
        "requested_coatings": ["AR_STANDARD"],
        "monocular_pd_od_mm": 31.5,
        "monocular_pd_os_mm": 31.5,
        "fitting_height_mm": 16.0,
    }
    payload.update(overrides)
    return payload


def create_progressive_rx_order_payload(
    patient_id: str, prescription_id: str, lens_design_id: str, **overrides
) -> dict:
    """The expedited progressive order: frame 21995 plus AR_PREMIUM and HARDCOAT."""
    payload = {
        "patient_id": patient_id,
        "prescription_id": prescription_id,
        "lens_design_id": lens_design_id,
        "frame_sku": "FRM-A22",
        "frame_retail_cents": 21995,
        "requested_coatings": ["AR_PREMIUM", "HARDCOAT"],
        "monocular_pd_od_mm": 31.0,
        "monocular_pd_os_mm": 30.0,
        "fitting_height_mm": 22.0,
        "expedite_requested": True,
    }
    payload.update(overrides)
    return payload


def create_frame_layout_payload(
    rx_order_id: str, expected_rx_order_version: int, **overrides
) -> dict:
    """The stock trace: a 50.0, b 28.0, ed 52.0, dbl 17.0."""
    payload = {
        "rx_order_id": rx_order_id,
        "expected_rx_order_version": expected_rx_order_version,
        "trace_source": "DIGITAL_TRACER",
        "a_mm": 50.0,
        "b_mm": 28.0,
        "ed_mm": 52.0,
        "dbl_mm": 17.0,
    }
    payload.update(overrides)
    return payload


def create_progressive_frame_layout_payload(
    rx_order_id: str, expected_rx_order_version: int, **overrides
) -> dict:
    """The wide trace: a 52.0, b 32.0, ed 55.0, dbl 18.0."""
    payload = {
        "rx_order_id": rx_order_id,
        "expected_rx_order_version": expected_rx_order_version,
        "trace_source": "DIGITAL_TRACER",
        "a_mm": 52.0,
        "b_mm": 32.0,
        "ed_mm": 55.0,
        "dbl_mm": 18.0,
    }
    payload.update(overrides)
    return payload


def create_lab_job_payload(rx_order_id: str, **overrides) -> dict:
    payload = {"rx_order_id": rx_order_id}
    payload.update(overrides)
    return payload


def create_lab_operation_payload(
    lab_job_id: str,
    expected_lab_job_version: int,
    operation_type: str,
    window_start: str,
    window_end: str,
    **overrides,
) -> dict:
    payload = {
        "lab_job_id": lab_job_id,
        "expected_lab_job_version": expected_lab_job_version,
        "operation_type": operation_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_edging_operation_payload(
    lab_job_id: str,
    expected_lab_job_version: int,
    bay_id: str,
    window_start: str = "2026-08-01T08:00:00Z",
    window_end: str = "2026-08-01T09:00:00Z",
    **overrides,
) -> dict:
    return create_lab_operation_payload(
        lab_job_id,
        expected_lab_job_version,
        "EDGING",
        window_start,
        window_end,
        bay_id=bay_id,
        **overrides,
    )


def create_surfacing_operation_payload(
    lab_job_id: str,
    expected_lab_job_version: int,
    machine_id: str,
    window_start: str = "2026-08-01T09:00:00Z",
    window_end: str = "2026-08-01T10:00:00Z",
    **overrides,
) -> dict:
    return create_lab_operation_payload(
        lab_job_id,
        expected_lab_job_version,
        "SURFACING",
        window_start,
        window_end,
        machine_id=machine_id,
        **overrides,
    )


# --------------------------------------------------------------------------
# Inspections and remakes
# --------------------------------------------------------------------------


def create_quality_inspection_payload(lab_job_id: str, eye: str, **overrides) -> dict:
    """Measurements exactly on the stock prescription, so the verdict passes."""
    payload = {
        "lab_job_id": lab_job_id,
        "eye": eye,
        "measured_sphere": -2.0,
        "measured_cylinder": -1.0,
        "measured_axis": 90,
        "measured_prism": 0.0,
    }
    payload.update(overrides)
    return payload


def create_remake_case_payload(lab_job_id: str, **overrides) -> dict:
    payload = {
        "lab_job_id": lab_job_id,
        "defect_codes": ["POWER_OUT_OF_TOL"],
        "warranty_claim": False,
    }
    payload.update(overrides)
    return payload


def create_adjudication_payload(adjudication_method: str, **overrides) -> dict:
    payload = {"adjudication_method": adjudication_method}
    payload.update(overrides)
    return payload


def create_settlement_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload
