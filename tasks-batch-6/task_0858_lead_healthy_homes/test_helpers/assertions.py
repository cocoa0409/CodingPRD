"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §2.9)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _assert_audit_only(data: dict):
    """Immutable audit record: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable audit record must not carry a version field"
    assert "updated_at" not in data, "immutable audit record must not carry an updated_at field"


def assert_child(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["income_tier"] in ("EXTREMELY_LOW", "VERY_LOW", "LOW", "MODERATE")
    assert isinstance(data["medicaid_enrolled"], bool)


def assert_blood_lead_test(data: dict):
    _assert_audit_only(data)
    assert data["result_class"] in ("CLASS_I", "CLASS_II", "CLASS_III", "BELOW_THRESHOLD")
    assert data["specimen_type"] in ("VENOUS", "CAPILLARY")
    assert data["test_kind"] in ("SCREENING", "DIAGNOSTIC", "FOLLOWUP")


def assert_dwelling(data: dict):
    _assert_common(data)
    assert isinstance(data["pre_1978"], bool)
    assert isinstance(data["year_built"], int)


def assert_case(data: dict):
    _assert_common(data)
    assert data["case_status"] in ("OPEN", "INVESTIGATION", "ENFORCEMENT", "CLOSED", "WITHDRAWN")
    assert data["medical_status"] in ("ELEVATED", "MONITORING", "RESOLVED")
    assert data["reference_basis"] in ("PROVISIONAL", "CONFIRMED")
    assert data["priority_class"] in ("CLASS_I", "CLASS_II", "CLASS_III")
    assert_case_hazard_invariants(data)


def assert_case_hazard_invariants(data: dict):
    """Conserved-count invariant (PRD §2.9): total == open + controlled, all >= 0."""
    open_c = data["open_hazard_count"]
    ctrl_c = data["controlled_hazard_count"]
    total_c = data["total_hazard_count"]
    assert open_c >= 0 and ctrl_c >= 0 and total_c >= 0, "hazard counts must be non-negative"
    assert total_c == open_c + ctrl_c, (
        f"total_hazard_count ({total_c}) must equal open ({open_c}) + controlled ({ctrl_c})"
    )


def assert_inspector(data: dict):
    _assert_common(data)
    assert isinstance(data["active"], bool)


def assert_investigation(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["hazard_finding_count"], int)


def assert_hazard_finding(data: dict):
    _assert_common(data)
    assert data["hazard_type"] in ("PAINT", "DUST", "SOIL", "WATER")
    assert data["severity"] in ("LOW", "MODERATE", "HIGH")
    assert data["control_status"] in ("OPEN", "CONTROLLED")


def assert_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "IN_REMEDIATION", "CLEARANCE_PENDING", "CLEARED", "VOID")
    assert isinstance(data["hazard_count"], int)


def assert_clearance_test(data: dict):
    _assert_audit_only(data)
    assert data["evaluated_result"] in ("PASS", "FAIL")


def assert_relocation_unit(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "OFFLINE")


def assert_relocation_placement(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "ENDED", "CANCELLED")
    assert isinstance(data["reimbursement_cents"], int)
    assert data["reimbursement_cents"] >= 0


def assert_contractor(data: dict):
    _assert_common(data)
    assert data["certification_status"] in ("PENDING", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED")


def assert_grant_fund(data: dict):
    _assert_common(data)
    assert_grant_ledger_invariant(data)


def assert_grant_ledger_invariant(data: dict):
    """Conserved-money invariant (PRD §2.6): available + reserved + spent == total; none negative."""
    total = data["total_budget_cents"]
    reserved = data["reserved_cents"]
    spent = data["spent_cents"]
    available = data["available_cents"]
    assert reserved >= 0 and spent >= 0 and available >= 0, "ledger fields must be non-negative"
    assert available + reserved + spent == total, (
        f"available ({available}) + reserved ({reserved}) + spent ({spent}) "
        f"must equal total_budget_cents ({total})"
    )


def assert_remediation_project(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "APPROVED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["estimated_cost_cents"], int)
