"""Payload factories — one per entity, input fields only (PRD §3, §4).

Each factory provides sensible defaults aligned with the canonical literals in constants.py
and accepts **overrides for the fields a given test needs to control.
"""

# Default datetimes used across setups.
_DEFAULT_PIS_DATE = "2026-01-01T00:00:00Z"
_DEFAULT_EFFECTIVE_DATE = "2026-01-15T00:00:00Z"


def create_project_payload(**overrides) -> dict:
    """Input fields: name, area_median_income_cents, minimum_set_aside, placed_in_service_date."""
    defaults = {
        "name": "Test Project",
        "area_median_income_cents": 9_600_000,
        "minimum_set_aside": "FORTY_SIXTY",
        "placed_in_service_date": _DEFAULT_PIS_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_building_payload(project_id: str, **overrides) -> dict:
    """Input fields: project_id, bin, eligible_basis_cents, credit_type,
    total_residential_units, total_residential_sqft."""
    defaults = {
        "project_id": project_id,
        "bin": "B-001",
        "eligible_basis_cents": 100_000_000,
        "credit_type": "NINE_PERCENT",
        "total_residential_units": 10,
        "total_residential_sqft": 10_000,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(building_id: str, **overrides) -> dict:
    """Input fields: building_id, unit_number, bedroom_count, sqft, utility_allowance_cents,
    ami_designation."""
    defaults = {
        "building_id": building_id,
        "unit_number": "U1",
        "bedroom_count": 1,
        "sqft": 1_000,
        "utility_allowance_cents": 9_000,
        "ami_designation": "AMI_50",
    }
    defaults.update(overrides)
    return defaults


def create_household_payload(project_id: str, **overrides) -> dict:
    """Input fields: project_id, head_name, household_size, all_full_time_students,
    student_exception? (optional, defaults to NONE server-side)."""
    defaults = {
        "project_id": project_id,
        "head_name": "Head Of Household",
        "household_size": 2,
        "all_full_time_students": False,
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(household_id: str, unit_id: str, **overrides) -> dict:
    """Input fields: household_id, unit_id, cert_type, annual_income_cents, effective_date."""
    defaults = {
        "household_id": household_id,
        "unit_id": unit_id,
        "cert_type": "INITIAL",
        "annual_income_cents": 3_000_000,
        "effective_date": _DEFAULT_EFFECTIVE_DATE,
    }
    defaults.update(overrides)
    return defaults


def lease_payload(household_id: str, **overrides) -> dict:
    """Input fields for POST /units/{id}/lease: household_id, monthly_rent_cents,
    rent_start_date, rent_end_date (unit_id comes from the path)."""
    defaults = {
        "household_id": household_id,
        "monthly_rent_cents": 80_000,
        "rent_start_date": "2026-02-01T00:00:00Z",
        "rent_end_date": "2027-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(building_id: str, **overrides) -> dict:
    """Input fields: building_id, window_start, window_end, inspected_on, deduction_points,
    has_exigent_health_safety? (optional, defaults false server-side)."""
    defaults = {
        "building_id": building_id,
        "window_start": "2026-03-01T00:00:00Z",
        "window_end": "2026-03-05T00:00:00Z",
        "inspected_on": "2026-03-03T00:00:00Z",
        "deduction_points": [5],
    }
    defaults.update(overrides)
    return defaults


def issue_form8609_payload(issuance_type: str, **overrides) -> dict:
    """Input fields: issuance_type, monthly_qualified_units? (FINAL only),
    expected_building_version? (FINAL only)."""
    defaults = {"issuance_type": issuance_type}
    defaults.update(overrides)
    return defaults


def approve_payload(decision: str = "APPROVE", **overrides) -> dict:
    """Input field for POST /certifications/{id}/approve: decision (APPROVE | REJECT)."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def recapture_payload(expected_building_version: int, **overrides) -> dict:
    """Input field for POST /buildings/{id}/recapture: expected_building_version."""
    defaults = {"expected_building_version": expected_building_version}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    """Input field for POST /_clock/set_current_utc: to_iso8601."""
    return {"to_iso8601": to_iso8601}
