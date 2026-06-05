"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

LEASE_STATES = ["DRAFT", "ACTIVE", "HOLDOVER", "TERMINATED"]
TI_DRAW_STATES = ["REQUESTED", "APPROVED", "REJECTED"]
RECON_STATES = ["DRAFT", "IN_REVIEW", "POSTED", "DISPUTED", "VOID"]
ESTOPPEL_STATES = ["ISSUED", "CONFIRMED", "DISPUTED"]
POOL_STATES = ["OPEN", "LOCKED"]
RECOVERABILITIES = ["RECOVERABLE", "NON_RECOVERABLE", "CAPPED_CONTROLLABLE"]
ESCALATION_TYPES = ["FIXED_PCT", "CPI", "NONE"]
LEDGER_TYPES = [
    "BASE_RENT", "PCT_RENT", "CAM_ESTIMATE", "CAM_TRUEUP",
    "TI_DRAW", "PAYMENT", "CREDIT_ADJUSTMENT",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data or data.get("version") is None, \
        "append-only entity must not carry a version field"


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["total_rentable_sqft"], int) and data["total_rentable_sqft"] > 0
    assert isinstance(data["occupied_sqft"], int) and data["occupied_sqft"] >= 0
    assert isinstance(data["gross_up_occupancy_pct"], (int, float))
    assert 0 < data["gross_up_occupancy_pct"] <= 1


def assert_expense_pool(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["pool_year"], int)
    assert data["pro_rata_denominator"] in ("TOTAL_RENTABLE", "OCCUPIED")
    assert isinstance(data["admin_fee_pct"], (int, float))
    assert data["status"] in POOL_STATES
    assert isinstance(data["total_recoverable_cents"], int)


def assert_expense_line_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["pool_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["recoverability"] in RECOVERABILITIES
    assert isinstance(data["is_variable"], bool)


def assert_tenant(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["contact_email"], str)


def assert_lease(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["tenant_id"])
    assert isinstance(data["leased_sqft"], int) and data["leased_sqft"] > 0
    assert isinstance(data["base_rent_cents_annual"], int)
    assert data["escalation_type"] in ESCALATION_TYPES
    assert isinstance(data["ti_drawn_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in LEASE_STATES


def assert_ti_draw(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in TI_DRAW_STATES


def assert_reconciliation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["pool_id"])
    assert isinstance(data["recon_year"], int)
    assert data["status"] in RECON_STATES


def assert_estoppel(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["asserted_balance_cents"], int)
    assert isinstance(data["asserted_base_rent_cents_annual"], int)
    assert data["status"] in ESTOPPEL_STATES


def assert_sales_report(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["period_year"], int)
    assert isinstance(data["gross_sales_cents"], int) and data["gross_sales_cents"] >= 0


def assert_ledger_entry(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["lease_id"])
    assert data["entry_type"] in LEDGER_TYPES
    assert isinstance(data["amount_cents"], int)
