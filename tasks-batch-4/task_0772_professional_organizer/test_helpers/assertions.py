"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates that a response object carries the common
resource properties (UUID id, ISO 8601 timestamps, integer version — PRD
Section 2.4) and the entity-specific fields the PRD promises.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["home_address"], str)


def assert_organizer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["active"], bool)


def assert_project(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCOPING", "ACTIVE", "WRAP_UP", "CLOSED", "CANCELLED"]
    assert data["billing_mode"] in ["HOURLY", "PROJECT"]
    assert isinstance(data["scope_rooms"], list)
    assert isinstance(data["projected_product_cost_cents"], int)
    assert isinstance(data["projected_haul_cost_cents"], int)
    assert isinstance(data["donation_credit_cents"], int)


def assert_session(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    assert isinstance(data["labor_cost_cents"], int)
    assert isinstance(data["is_overtime"], bool)


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "LOGGED", "SCHEDULED_HAUL", "SCHEDULED_DONATION", "HAULED", "DONATED", "KEPT",
    ]
    assert data["disposition"] in ["KEEP", "HAUL", "DONATE", "SELL"]
    assert isinstance(data["haul_fee_cents"], int)


def assert_product_line(data: dict):
    _assert_common(data)
    assert data["status"] in ["QUOTED", "ORDERED", "DELIVERED", "CANCELLED"]
    assert data["category"] in ["BIN", "SHELVING", "SYSTEM", "LABELING"]
    assert isinstance(data["client_price_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "DISPUTED", "PAID"]
    assert data["billing_mode"] in ["HOURLY", "PROJECT"]
    for field in [
        "labor_subtotal_cents", "product_subtotal_cents", "haul_subtotal_cents",
        "donation_credit_cents", "move_addon_cents", "subtotal_cents",
        "discount_cents", "tax_cents", "grand_total_cents",
    ]:
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_maintenance_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "CANCELLED"]
    assert data["cadence"] in ["MONTHLY", "QUARTERLY", "BIANNUAL"]
    assert isinstance(data["visits_per_year"], int)
