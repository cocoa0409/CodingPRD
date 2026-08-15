"""Entity assertions and domain invariant checkers for the septic-ops API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}: version must be an integer"


def assert_installer_company(data: dict):
    _assert_common_fields(data, "InstallerCompany")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["county_codes"], list)


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert "education_completed_at" in data


def assert_site(data: dict):
    _assert_common_fields(data, "Site")
    assert isinstance(data["parcel_id"], str) and data["parcel_id"]
    assert isinstance(data["address_line"], str)
    assert isinstance(data["county_code"], str)
    assert isinstance(data["current_period_index"], int)
    assert isinstance(data["seasonal_freeze_until"], int)
    assert data["status"] in ("OPEN", "FROZEN", "CLOSED")
    assert isinstance(data["high_water_table"], bool)


def assert_soil_evaluation(data: dict):
    _assert_common_fields(data, "SoilEvaluation")
    assert data["soil_class"] in ("SAND", "LOAM", "CLAY_LOAM", "CLAY")
    assert isinstance(data["limiting_layer_inches"], int)
    assert 1 <= data["limiting_layer_inches"] <= 240
    assert isinstance(data["evaluation_date_period"], int)
    assert data["status"] in ("RECORDED", "SUPERSEDED", "VOIDED")


def assert_percolation_test(data: dict):
    _assert_common_fields(data, "PercolationTest")
    assert 0.5 <= float(data["minutes_per_inch"]) <= 240.0
    assert isinstance(data["test_pit_count"], int)
    assert 2 <= data["test_pit_count"] <= 12
    assert isinstance(data["test_date_period"], int)
    assert data["status"] in ("RECORDED", "SUPERSEDED", "VOIDED")


def assert_staff_member(data: dict, label: str):
    _assert_common_fields(data, label)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["installer_company_id"], str) and data["installer_company_id"]


def assert_soil_scientist(data: dict):
    assert_staff_member(data, "SoilScientist")
    assert isinstance(data["license_number"], str) and data["license_number"]


def assert_system_designer(data: dict):
    assert_staff_member(data, "SystemDesigner")
    assert isinstance(data["license_number"], str) and data["license_number"]


def assert_inspector(data: dict):
    assert_staff_member(data, "Inspector")
    assert isinstance(data["license_number"], str) and data["license_number"]


def assert_health_officer(data: dict):
    assert_staff_member(data, "HealthOfficer")
    assert isinstance(data["badge_number"], str) and data["badge_number"]


def assert_project_manager(data: dict):
    assert_staff_member(data, "ProjectManager")
    assert isinstance(data["employee_number"], str) and data["employee_number"]


def assert_system_design(data: dict):
    _assert_common_fields(data, "SystemDesign")
    assert isinstance(data["bedroom_count"], int) and 1 <= data["bedroom_count"] <= 12
    assert data["system_type"] in ("GRAVITY", "PRESSURE_DISTRIBUTION", "MOUND", "AEROBIC")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED", "WITHDRAWN")
    assert isinstance(data["design_version"], int) and data["design_version"] >= 1
    assert float(data["design_daily_flow_gpd"]) > 0
    assert float(data["required_absorption_area_sqft"]) > 0
    assert float(data["tank_capacity_gal"]) > 0
    assert float(data["reserve_area_sqft"]) > 0


def assert_permit(data: dict):
    _assert_common_fields(data, "Permit")
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert isinstance(data["issued_period"], int)
    assert isinstance(data["expires_period"], int)
    assert data["expires_period"] == data["issued_period"] + 5, (
        "Permit validity window is six periods inclusive: "
        f"expires_period {data['expires_period']} != issued_period {data['issued_period']} + 5"
    )
    assert data["status"] in ("ISSUED", "SUSPENDED", "EXPIRED", "FINALIZED", "REVOKED")


def assert_installation(data: dict):
    _assert_common_fields(data, "Installation")
    assert isinstance(data["crew_lead"], str) and data["crew_lead"]
    assert data["status"] in (
        "NOT_STARTED", "ROUGH_IN_PROGRESS", "TANK_SET", "FIELD_INSTALLED",
        "READY_FOR_FINAL", "COMPLETED", "FAILED_HOLD", "ABANDONED",
    )


def assert_inspection(data: dict):
    _assert_common_fields(data, "Inspection")
    assert data["hold_point"] in ("TANK_SET", "FIELD_LAYOUT", "FINAL")
    assert data["result"] in ("PENDING", "PASSED", "FAILED")
    assert isinstance(data["scheduled_period"], int) and data["scheduled_period"] >= 0


def assert_material_verification(data: dict):
    _assert_common_fields(data, "MaterialVerification")
    assert data["material_kind"] in ("TANK", "PIPE", "AGGREGATE", "CHAMBER", "PUMP")
    assert float(data["quantity"]) > 0
    assert int(data["unit_cost_cents"]) >= 0
    assert isinstance(data["verified"], bool)


def assert_variance_request(data: dict):
    _assert_common_fields(data, "VarianceRequest")
    assert data["relief_kind"] in (
        "SETBACK_REDUCTION", "AREA_REDUCTION", "HIGH_WATER_TABLE", "REPAIR_IN_KIND",
    )
    assert isinstance(data["justification"], str) and len(data["justification"]) >= 20
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "WITHDRAWN")


def assert_maintenance_contract(data: dict):
    _assert_common_fields(data, "MaintenanceContract")
    assert isinstance(data["start_period"], int)
    assert isinstance(data["end_period"], int)
    assert data["end_period"] > data["start_period"]
    assert int(data["annual_fee_cents"]) > 0
    assert int(data["prorated_fee_cents"]) > 0
    assert data["status"] in ("ACTIVE", "LAPSED", "CANCELLED", "EXPIRED")


def assert_maintenance_visit(data: dict):
    _assert_common_fields(data, "MaintenanceVisit")
    assert isinstance(data["visit_period"], int)
    assert isinstance(data["findings"], str)
    assert isinstance(data["alarm_condition"], bool)
    assert isinstance(data["technician_name"], str) and data["technician_name"]


def assert_repair_case(data: dict):
    _assert_common_fields(data, "RepairCase")
    assert data["failure_kind"] in (
        "HYDRAULIC_OVERLOAD", "STRUCTURAL_COLLAPSE", "ROOT_INTRUSION", "HIGH_WATER_INTRUSION",
    )
    assert isinstance(data["diagnosis_note"], str) and len(data["diagnosis_note"]) >= 20
    assert data["remedy"] in ("UNDECIDED", "REPAIR_IN_KIND", "REPLACEMENT")
    assert data["status"] in ("OPEN", "TRIAGED", "IN_REMEDIATION", "RESOLVED", "CLOSED")
