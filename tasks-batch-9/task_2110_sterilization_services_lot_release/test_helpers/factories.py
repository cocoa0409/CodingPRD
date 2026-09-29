"""Payload factories - one per resource, input fields only."""

from .constants import TEST_DEFAULTS


def create_customer_payload(**overrides) -> dict:
    payload = {
        "name": "Acme Medical",
        "account_code": "ACME-01",
        "contracted_modalities": ["ETO", "GAMMA"],
    }
    payload.update(overrides)
    return payload


def create_product_payload(customer_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "product_code": "P1",
        "pallet_mass_kg": TEST_DEFAULTS["PALLET_MASS_KG"],
        "pallet_volume_m3": TEST_DEFAULTS["PALLET_VOLUME_M3"],
        "max_allowed_dose_kgy": TEST_DEFAULTS["MAX_ALLOWED_DOSE_KGY"],
        "max_cumulative_dose_kgy": TEST_DEFAULTS["MAX_CUMULATIVE_DOSE_KGY"],
        "eto_residual_limit_ppm": TEST_DEFAULTS["ETO_RESIDUAL_LIMIT_PPM"],
        "ech_residual_limit_ppm": TEST_DEFAULTS["ECH_RESIDUAL_LIMIT_PPM"],
        "requires_aeration": False,
    }
    payload.update(overrides)
    return payload


def create_permit_payload(**overrides) -> dict:
    payload = {
        "permit_code": "AP-2026",
        "permit_year": 2026,
        "annual_allowance_kg": TEST_DEFAULTS["ANNUAL_ALLOWANCE_KG"],
        "max_concurrent_eto_cycles": TEST_DEFAULTS["MAX_CONCURRENT_ETO_CYCLES"],
    }
    payload.update(overrides)
    return payload


def create_chamber_payload(permit_id: str, modality: str = "GAMMA", **overrides) -> dict:
    eto = modality == "ETO"
    payload = {
        "permit_id": permit_id,
        "chamber_code": "CH-E1" if eto else "CH-G1",
        "modality": modality,
        "pallet_capacity": TEST_DEFAULTS["PALLET_CAPACITY"],
        "turnaround_minutes": (
            TEST_DEFAULTS["ETO_TURNAROUND_MINUTES"]
            if eto
            else TEST_DEFAULTS["GAMMA_TURNAROUND_MINUTES"]
        ),
        "abatement_efficiency_pct": (
            TEST_DEFAULTS["ETO_ABATEMENT_EFFICIENCY_PCT"] if eto else 0.0
        ),
    }
    payload.update(overrides)
    return payload


def create_recipe_payload(modality: str = "GAMMA", **overrides) -> dict:
    eto = modality == "ETO"
    payload = {
        "recipe_code": "RE" if eto else "RG",
        "modality": modality,
        "density_min_g_per_cm3": TEST_DEFAULTS["DENSITY_MIN"],
        "density_max_g_per_cm3": TEST_DEFAULTS["DENSITY_MAX"],
        "target_dose_kgy": TEST_DEFAULTS["TARGET_DOSE_KGY"],
        "min_dose_kgy": TEST_DEFAULTS["MIN_DOSE_KGY"],
        "max_dose_kgy": TEST_DEFAULTS["MAX_DOSE_KGY"],
        "dose_basis": "ROUTINE_MEAN",
        "aeration_base_hours": TEST_DEFAULTS["ETO_AERATION_BASE_HOURS"] if eto else 0,
        "required_min_zone_dosimeters": 1,
        "required_routine_dosimeters": 1,
        "required_biological_indicators": 0,
    }
    payload.update(overrides)
    return payload


def create_qualification_payload(product_id: str, recipe_id: str, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "recipe_id": recipe_id,
        "method": "VDMAX_25",
        "verification_dose_kgy": TEST_DEFAULTS["VERIFICATION_DOSE_KGY"],
        "sal_exponent": TEST_DEFAULTS["SAL_EXPONENT"],
    }
    payload.update(overrides)
    return payload


def create_dose_audit_payload(**overrides) -> dict:
    payload = {
        "performed_at": TEST_DEFAULTS["AUDIT_PERFORMED_AT"],
        "samples_tested": 100,
        "positives": 0,
        "verification_dose_kgy_applied": TEST_DEFAULTS["VERIFICATION_DOSE_KGY"],
    }
    payload.update(overrides)
    return payload


def create_lot_payload(customer_id: str, product_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "product_id": product_id,
        "lot_code": "L-001",
        "total_pallet_count": 2,
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(chamber_id: str, recipe_id: str, **overrides) -> dict:
    payload = {
        "chamber_id": chamber_id,
        "recipe_id": recipe_id,
        "cycle_code": "C-001",
        "scheduled_start_at": "2026-08-11T00:00:00Z",
        "scheduled_end_at": "2026-08-11T06:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_load_position_payload(lot_id: str, expected_cycle_version: int, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "position_index": 1,
        "zone": "MIN_DOSE",
        "pallet_count": 2,
        "expected_cycle_version": expected_cycle_version,
    }
    payload.update(overrides)
    return payload


def create_indicator_payload(**overrides) -> dict:
    payload = {
        "indicator_type": "DOSIMETER",
        "placement_zone": "MIN_DOSE",
        "serial_code": "D-MIN",
    }
    payload.update(overrides)
    return payload


def create_adverse_event_payload(expected_lot_version: int, **overrides) -> dict:
    payload = {
        "event_type": "STERILITY_COMPLAINT",
        "severity": "HIGH",
        "description": "Field sterility complaint on implanted device",
        "expected_lot_version": expected_lot_version,
    }
    payload.update(overrides)
    return payload


def create_residual_test_payload(**overrides) -> dict:
    payload = {"eto_residual_ppm": 1.0, "ech_residual_ppm": 1.0}
    payload.update(overrides)
    return payload
