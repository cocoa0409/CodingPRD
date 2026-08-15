"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_ledger_line_fields(data: dict):
    """Append-only ledger lines (PRD §2.4): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger line must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "append-only ledger line must not carry version (PRD §2.4)"


def assert_service_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["base_direct_cost"] >= 0
    assert isinstance(data["budgeted_volume"], int) and data["budgeted_volume"] > 0
    assert data["status"] in ["ACTIVE", "ARCHIVED"]
    for field in ("total_direct_cost", "total_revenue", "contribution_margin"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"


def assert_cost_center(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["cost_type"] in ["DIRECT", "INDIRECT", "OVERHEAD"]
    assert data["cost_behavior"] in ["FIXED", "VARIABLE"]
    assert data["allocated_cost"] > 0
    assert data["capacity_measure"] in ["MINUTES", "RVU", "NONE"]
    assert data["status"] in ["ACTIVE", "ARCHIVED"]


def assert_physician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["npi"], str) and len(data["npi"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["specialty"], str) and len(data["specialty"]) > 0
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_drg(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["drg_code"], str) and len(data["drg_code"]) > 0
    assert isinstance(data["description"], str)
    assert data["target_cost"] >= 0
    assert data["base_rate"] >= 0


def assert_cost_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["service_line_id"], str)
    assert data["allocation_basis"] in ["TDABC", "RVU"]
    assert data["rate_factor"] >= 0
    assert isinstance(data["overhead_cost_center_id"], str)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED", "ARCHIVED"]
    assert isinstance(data["effective_period"], str)


def assert_cost_model_refresh(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["model_id"], str)
    assert isinstance(data["period"], str)
    assert isinstance(data["proposed_rates"], list)
    assert isinstance(data["data_quality_score"], (int, float))
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED", "APPLIED"]


def assert_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["service_line_id"], str)
    assert isinstance(data["physician_id"], str)
    assert isinstance(data["drg_id"], str)
    assert isinstance(data["cost_model_id"], str)
    assert isinstance(data["period"], str)
    assert data["expected_reimbursement"] >= 0
    assert data["status"] in ["DRAFT", "POSTED", "VOIDED", "LOCKED"]
    for field in ("total_direct_cost", "total_indirect_allocated", "total_cost", "margin"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"


def assert_activity_cost_line(data: dict):
    _assert_ledger_line_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["cost_center_id"], str)
    assert data["quantity"] > 0


def assert_implant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["item_code"], str)
    assert isinstance(data["vendor"], str)
    assert data["unit_cost"] > 0
    assert isinstance(data["quantity"], int) and data["quantity"] > 0


def assert_supply_line(data: dict):
    _assert_ledger_line_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["supply_code"], str)
    assert data["unit_cost"] > 0
    assert isinstance(data["quantity"], int) and data["quantity"] > 0


def assert_payer_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["service_line_id"], str)
    assert isinstance(data["payer_name"], str)
    assert data["payer_type"] in ["MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY"]
    assert data["contracted_rate"] > 0
    assert isinstance(data["effective_period"], str)
    assert data["status"] in ["ACTIVE", "TERMINATED"]


def assert_budget_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cost_center_id"], str)
    assert isinstance(data["period"], str)
    assert data["static_budget_amount"] > 0
    assert data["status"] in ["OPEN", "LOCKED"]
    for field in ("actual_indirect_volume", "flexed_overhead", "variance_amount"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert data["variance_direction"] in ["FAVORABLE", "UNFAVORABLE", "ON_BUDGET"]
