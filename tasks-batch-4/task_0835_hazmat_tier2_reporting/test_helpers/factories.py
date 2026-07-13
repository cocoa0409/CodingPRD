"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _unique_suffix() -> str:
    return f"{next(_counter):06d}"


def create_facility_payload(**overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "name": f"Test Facility {suffix}",
        "epa_facility_id": f"EPA-{suffix}",
        "state_code": "TX",
        "county": "Harris",
        "operator_name": f"Test Operator {suffix}",
    }
    defaults.update(overrides)
    return defaults


def create_chemical_payload(**overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "cas_number": f"CAS-{suffix}",
        "name": f"Test Chemical {suffix}",
        "is_ehs": False,
        "rq_lbs": 1000,
        "hazard_weight": 0.2,
        "physical_state": "SOLID",
    }
    defaults.update(overrides)
    return defaults


def create_ehs_chemical_payload(**overrides) -> dict:
    """Convenience: EHS chemical carries tpq_lbs (required when is_ehs)."""
    suffix = _unique_suffix()
    defaults = {
        "cas_number": f"CAS-EHS-{suffix}",
        "name": f"Test EHS Chemical {suffix}",
        "is_ehs": True,
        "tpq_lbs": 100,
        "rq_lbs": 10,
        "hazard_weight": 0.5,
        "physical_state": "GAS",
    }
    defaults.update(overrides)
    return defaults


def create_chemical_inventory_payload(facility_id, chemical_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "chemical_id": chemical_id,
        "reporting_year": 2025,
        "max_daily_amount_lbs": 200,
        "average_daily_amount_lbs": 150,
        "days_on_site": 300,
        "storage_type": "CYLINDER",
    }
    defaults.update(overrides)
    return defaults


def create_tier_ii_filing_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "reporting_year": 2025,
    }
    defaults.update(overrides)
    return defaults


def create_sds_payload(facility_id, chemical_id, expected_facility_version, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "chemical_id": chemical_id,
        "document_ref": "sds://document-v1",
        "revision_date": "2025-01-02T00:00:00Z",
        "expected_facility_version": expected_facility_version,
    }
    defaults.update(overrides)
    return defaults


def create_release_notification_payload(facility_id, chemical_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "chemical_id": chemical_id,
        "release_datetime": "2026-02-01T00:00:00Z",
        "quantity_released_lbs": 100,
        "medium": "AIR",
    }
    defaults.update(overrides)
    return defaults


def create_lepc_notice_payload(release_id, **overrides) -> dict:
    defaults = {
        "release_id": release_id,
        "notice_type": "VERBAL",
        "recipient": "LEPC",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "permit_type": "OPERATING",
        "issued_date": "2026-01-01T00:00:00Z",
        "expiry_date": "2027-01-01T00:00:00Z",
        "fee_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "inspector_id": "INSP-1",
        "scheduled_date": "2026-04-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_compliance_case_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
    }
    defaults.update(overrides)
    return defaults


def create_risk_management_plan_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "program_level": 2,
        "submitted_date": "2025-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
