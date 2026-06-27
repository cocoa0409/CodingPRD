"""Payload factories — one per entity, input fields only (Mold Remediation PRD)."""
from .constants import TEST_DEFAULTS, THRESHOLDS


def create_worker_payload(**overrides) -> dict:
    """Worker registration. cert_type one of ASBESTOS|LEAD|MOLD|HYGIENIST."""
    defaults = {
        "full_name": "Test Worker",
        "cert_type": "MOLD",
        "cert_expires_at": TEST_DEFAULTS["CERT_EXPIRES_AT"],
        "ppe_fit_test_at": TEST_DEFAULTS["PPE_FIT_TEST_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    """Project. hazard_class one of ASBESTOS|LEAD|MOLD."""
    defaults = {
        "site_name": "Test Site",
        "hazard_class": "MOLD",
        "structure_sqft": TEST_DEFAULTS["STRUCTURE_SQFT"],
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(project_id: str, assessor_worker_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "assessor_worker_id": assessor_worker_id,
        "area_label": "Test Area",
    }
    defaults.update(overrides)
    return defaults


def create_sample_payload(assessment_id: str, project_id: str, sample_type: str,
                          **overrides) -> dict:
    """Sample. AIR requires volume_liters>0; SURFACE forbids it."""
    defaults = {
        "assessment_id": assessment_id,
        "project_id": project_id,
        "sample_type": sample_type,
        "collected_at": TEST_DEFAULTS["PAST_COLLECTED_AT"],
    }
    if sample_type == "AIR":
        defaults["volume_liters"] = 100
    defaults.update(overrides)
    return defaults


def create_zone_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "zone_label": "Z1",
        "required_pressure_pa": TEST_DEFAULTS["REQUIRED_PRESSURE_PA"],
    }
    defaults.update(overrides)
    return defaults


def create_pressure_log_payload(zone_id: str, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "reading_pa": TEST_DEFAULTS["COMPLIANT_READING_PA"],
        "reading_at": TEST_DEFAULTS["PAST_READING_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_abatement_order_payload(project_id: str, zone_id: str, lead_worker_id: str,
                                   **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "zone_id": zone_id,
        "lead_worker_id": lead_worker_id,
        "abatement_type": "MOLD",
        "planned_weight_kg": 50,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(abatement_order_id: str, worker_id: str, **overrides) -> dict:
    defaults = {
        "abatement_order_id": abatement_order_id,
        "worker_id": worker_id,
        "shift_start_at": TEST_DEFAULTS["SHIFT_START_AT"],
        "shift_end_at": TEST_DEFAULTS["SHIFT_END_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_manifest_payload(abatement_order_id: str, project_id: str, **overrides) -> dict:
    defaults = {
        "abatement_order_id": abatement_order_id,
        "project_id": project_id,
        "hauler_name": TEST_DEFAULTS["HAULER_NAME"],
        "manifest_weight_kg": 50,
    }
    defaults.update(overrides)
    return defaults


def create_clearance_test_payload(project_id: str, zone_id: str, abatement_order_id: str,
                                  sampler_worker_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "zone_id": zone_id,
        "abatement_order_id": abatement_order_id,
        "sampler_worker_id": sampler_worker_id,
        "clearance_air_count": 10,
        "clearance_volume_liters": 100,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "permit_type": "NESHAP_NOTIFICATION",
        "postmarked_at": "2026-01-01T00:00:00Z",
        "work_start_at": "2026-01-13T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_insurance_claim_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "policy_number": "POL-1",
        "deductible_cents": 0,
        "coverage_limit_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults
