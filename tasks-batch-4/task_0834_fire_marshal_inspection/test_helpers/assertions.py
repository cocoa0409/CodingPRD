"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert isinstance(data["owner_name"], str)
    assert data["occupancy_classification"] in [
        "ASSEMBLY", "BUSINESS", "EDUCATIONAL", "FACTORY", "HIGH_HAZARD",
        "INSTITUTIONAL", "MERCANTILE", "RESIDENTIAL", "STORAGE", "UTILITY",
    ]
    assert data["construction_type"] in ["TYPE_I", "TYPE_II", "TYPE_III", "TYPE_IV", "TYPE_V"]
    assert isinstance(data["total_floor_area_sqft"], int) and data["total_floor_area_sqft"] > 0
    assert isinstance(data["stories"], int) and data["stories"] >= 1
    assert isinstance(data["occupant_load"], int) and data["occupant_load"] >= 0
    assert isinstance(data["design_occupant_load"], int) and data["design_occupant_load"] >= 0
    assert isinstance(data["required_exits"], int) and data["required_exits"] >= 1
    assert isinstance(data["required_fire_flow_gpm"], int) and data["required_fire_flow_gpm"] >= 0
    assert isinstance(data["open_violation_count"], int) and data["open_violation_count"] >= 0
    assert isinstance(data["fees_paid_cents"], int)


def assert_permit_application(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "UNDER_REVIEW", "CORRECTIONS_REQUIRED", "APPROVED", "ISSUED"]
    assert data["permit_type"] in ["CONSTRUCTION", "TENANT_IMPROVEMENT", "HAZMAT", "TANK"]
    assert isinstance(data["project_valuation_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert isinstance(data["resubmit_count"], int)


def assert_plan_review(data: dict):
    _assert_common(data)
    for axis in ("sprinkler_status", "alarm_status", "egress_status"):
        assert data[axis] in ["UNDER_REVIEW", "APPROVED", "CORRECTIONS_REQUIRED"]
    assert data["overall_status"] in ["OPEN", "APPROVED"]
    assert isinstance(data["correction_cycles"], int)


def assert_permit(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "REVOKED"]
    assert isinstance(data["final_fee_cents"], int)
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["inspection_type"] in ["PERIODIC", "COMPLAINT", "RE_INSPECTION", "FINAL"]
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED"]


def assert_violation(data: dict):
    _assert_common(data)
    assert data["severity"] in ["MINOR", "MAJOR", "IMMINENT_HAZARD"]
    assert data["status"] in ["OPEN", "ABATED", "VERIFIED", "ESCALATED"]
    assert isinstance(data["code_section"], str)


def assert_abatement_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "COMPLIED", "OVERDUE", "ESCALATED", "SUPERSEDED"]
    assert isinstance(data["is_active"], bool)
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("deadline", "")), "deadline must be ISO 8601"


def assert_certificate(data: dict):
    _assert_common(data)
    assert data["occupancy_status"] in ["VALID", "SUSPENDED", "REVOKED"]
    assert data["placard_status"] in ["GREEN", "YELLOW", "RED"]


def assert_hydrant(data: dict):
    _assert_common(data)
    assert isinstance(data["location_desc"], str)


def assert_flow_test(data: dict):
    _assert_common(data)
    assert isinstance(data["available_flow_at_20psi"], int)
    assert is_iso8601_timestamp(data.get("valid_until", "")), "valid_until must be ISO 8601"
