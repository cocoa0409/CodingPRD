"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_asset_class(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["class_code"], str) and data["class_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capitalization_threshold_cents"], int)
    assert isinstance(data["default_useful_life_months"], int)
    assert data["default_useful_life_months"] > 0
    assert data["book_method"] in ("STRAIGHT_LINE", "DOUBLE_DECLINING")
    assert data["tax_method"] in ("MACRS_5YR", "MACRS_7YR", "TAX_STRAIGHT_LINE")
    assert isinstance(data["bonus_depreciation_allowed"], bool)


def assert_capital_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_code"], str) and data["project_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("asset_class_id", ""))
    assert isinstance(data["total_accumulated_cents"], int)
    assert data["total_accumulated_cents"] >= 0
    assert data["status"] in ("OPEN", "CAPITALIZED", "CANCELLED")


def assert_cip_cost_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["cost_type"] in ("MATERIAL", "LABOR", "VENDOR_INVOICE", "OTHER")
    assert isinstance(data["incurred_date"], str)
    assert data["status"] in ("POSTED", "REVERSED")


def assert_fixed_asset(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert isinstance(data["description"], str)
    assert is_valid_uuid(data.get("asset_class_id", ""))
    assert data["source"] in ("PURCHASE", "CIP_CAPITALIZATION",
                              "COMPONENT_ADDITION")
    assert isinstance(data["acquisition_cost_cents"], int)
    assert data["acquisition_cost_cents"] > 0
    assert isinstance(data["salvage_value_cents"], int)
    assert isinstance(data["useful_life_months"], int)
    assert data["book_method"] in ("STRAIGHT_LINE", "DOUBLE_DECLINING")
    assert data["tax_method"] in ("MACRS_5YR", "MACRS_7YR", "TAX_STRAIGHT_LINE")
    assert isinstance(data["bonus_elected"], bool)
    assert isinstance(data["cost_center"], str)
    assert isinstance(data["location"], str)
    assert data["status"] in ("DRAFT", "IN_SERVICE", "FULLY_DEPRECIATED",
                              "DISPOSED")
    assert isinstance(data["accumulated_book_cents"], int)
    assert isinstance(data["accumulated_tax_cents"], int)
    assert isinstance(data["impairment_total_cents"], int)
    assert isinstance(data["net_book_value_cents"], int)
    assert isinstance(data["open_inventory_exception"], bool)


def assert_depreciation_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert data["status"] in ("OPEN", "POSTED")
    assert isinstance(data["entries_created_count"], int)
    assert isinstance(data["total_book_amount_cents"], int)
    assert isinstance(data["total_tax_amount_cents"], int)


def assert_depreciation_entry(data: dict):
    """Ledger lines are append-only: id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger lines must not carry updated_at"
    assert "version" not in data, "ledger lines must not carry version"
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data["ledger"] in ("BOOK", "TAX")
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["source"] in ("RUN", "DISPOSAL_FINAL")


def assert_disposal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data["disposal_type"] in ("SALE", "SCRAP", "TRANSFER")
    assert isinstance(data["effective_date"], str)
    assert data["status"] in ("REQUESTED", "APPROVED", "POSTED", "REJECTED")


def assert_inventory_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["scope_type"] in ("ALL", "LOCATION", "COST_CENTER")
    assert data["status"] in ("COUNTING", "RECONCILING", "CLOSED")
    for counter in ("expected_count", "matched_count", "missing_count",
                    "mismatch_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_inventory_count_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("run_id", ""))
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data["reconciliation_status"] in (
        "PENDING", "MATCHED", "LOCATION_MISMATCH", "MISSING",
    )


def assert_impairment_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data["indicator"] in ("DAMAGE", "OBSOLESCENCE", "MARKET_DECLINE")
    assert data["source"] in ("MANUAL", "INVENTORY")
    assert data["status"] in ("OPEN", "WRITTEN_DOWN", "DISMISSED")


def assert_external_schedule(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data["schedule_type"] in ("PROPERTY_TAX", "INSURANCE")
    assert isinstance(data["schedule_year"], int)
    assert data["status"] in ("IMPORTED", "APPLIED")


def assert_asset_monetary_invariants(data: dict):
    """PRD §3.2: net book value is cost minus book depreciation minus impairment."""
    assert data["net_book_value_cents"] == (
        data["acquisition_cost_cents"]
        - data["accumulated_book_cents"]
        - data["impairment_total_cents"]
    ), (
        f"net_book_value_cents {data['net_book_value_cents']} != cost "
        f"{data['acquisition_cost_cents']} - book {data['accumulated_book_cents']}"
        f" - impairment {data['impairment_total_cents']}"
    )
    assert data["accumulated_book_cents"] >= 0
    assert data["accumulated_tax_cents"] >= 0
    assert data["impairment_total_cents"] >= 0
