"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_PROJECT_WORKFLOW = {"DRAFT", "MEASURED", "ESTIMATED", "ORDERED", "SCHEDULED",
                     "IN_PROGRESS", "COMPLETED", "CANCELLED"}
_PROJECT_COMPLIANCE = {"PENDING_CLEARANCE", "PERMIT_FILED", "CLEARED", "BLOCKED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_project(data: dict):
    _assert_common(data)
    assert data["workflow_status"] in _PROJECT_WORKFLOW, f"unexpected workflow_status {data['workflow_status']}"
    assert data["compliance_status"] in _PROJECT_COMPLIANCE, f"unexpected compliance_status {data['compliance_status']}"
    assert isinstance(data["contract_total_cents"], int)
    assert isinstance(data["retainage_held_cents"], int)
    assert isinstance(data["amount_released_cents"], int)
    assert isinstance(data["property_address"], str) and len(data["property_address"]) > 0
    assert isinstance(data["hoa_required"], bool)


def assert_project_cash_invariants(data: dict):
    """Cash ledger invariants that must hold after any project operation."""
    assert data["amount_released_cents"] >= 0, "amount_released_cents must be non-negative"
    assert data["retainage_held_cents"] >= 0, "retainage_held_cents must be non-negative"


def assert_homeowner_client(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["annual_income_cents"], int)
    assert isinstance(data["monthly_debt_cents"], int)


def assert_staff_member(data: dict):
    _assert_common(data)
    assert data["role_code"] in {"ESTIMATOR", "PROJECT_MANAGER", "FINANCE_OFFICER"}
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_measurement(data: dict):
    _assert_common(data)
    assert isinstance(data["net_siding_sqft"], (int, float))
    assert data["net_siding_sqft"] >= 0, "net_siding_sqft must be non-negative"
    assert isinstance(data["color_code"], str) and len(data["color_code"]) > 0


def assert_estimate(data: dict):
    _assert_common(data)
    assert data["status"] in {"DRAFT", "BASELINE"}
    assert isinstance(data["line_subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["estimate_total_cents"], int)


def assert_line_item(data: dict):
    _assert_common(data)
    assert data["scope_kind"] in {"SIDING", "TRIM", "WRAP"}
    assert isinstance(data["extended_cents"], int)


def assert_permit(data: dict):
    _assert_common(data)
    assert data["status"] in {"FILED", "ISSUED", "REJECTED"}


def assert_hoa_approval(data: dict):
    _assert_common(data)
    assert data["status"] in {"SUBMITTED", "APPROVED", "DENIED"}


def assert_material_order(data: dict):
    _assert_common(data)
    assert data["status"] in {"PLACED", "CONFIRMED", "BACKORDERED", "DELIVERED", "CANCELLED"}


def assert_change_order(data: dict):
    _assert_common(data)
    assert data["status"] in {"SUBMITTED", "NEGOTIATING", "APPROVED", "REJECTED", "WITHDRAWN"}
    assert isinstance(data["pm_approved"], bool)
    assert isinstance(data["client_approved"], bool)
    assert isinstance(data["delta_cents"], int)


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["max_wind_mph"] > 0


def assert_work_schedule(data: dict):
    _assert_common(data)
    assert data["status"] in {"PROPOSED", "CONFIRMED", "COMPLETED", "CANCELLED", "WEATHER_HOLD"}
    assert data["milestone"] in {"WRAP_INSTALL", "SIDING_INSTALL", "TRIM_FINISH"}


def assert_progress_draw(data: dict):
    _assert_common(data)
    assert data["status"] in {"REQUESTED", "APPROVED", "RELEASED", "CLAWED_BACK", "REJECTED"}
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["retainage_cents"], int)
    assert isinstance(data["net_released_cents"], int)


def assert_warranty(data: dict):
    _assert_common(data)
    assert data["warranty_kind"] in {"LIFETIME_MATERIAL", "WORKMANSHIP"}
    assert data["status"] in {"PENDING", "ACTIVE", "VOID"}


def assert_financing_application(data: dict):
    _assert_common(data)
    assert data["status"] in {"SUBMITTED", "APPROVED", "DECLINED"}
    assert isinstance(data["monthly_payment_cents"], int)
    assert isinstance(data["dti_ratio"], (int, float))
