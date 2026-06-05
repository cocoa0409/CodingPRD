"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["vendor_type"] in ("HARDWARE", "SOFTWARE", "BOTH")
    assert isinstance(data["support_email"], str)
    assert isinstance(data["active"], bool)


def assert_employee(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["department"], str)
    assert isinstance(data["max_assigned_assets"], int) and data["max_assigned_assets"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "OFFBOARDED")
    assert isinstance(data["open_checkout_count"], int) and data["open_checkout_count"] >= 0


def assert_software_product(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["license_model"] in ("PER_SEAT", "PER_CORE")
    assert data["compliance_status"] in ("COMPLIANT", "OVER_DEPLOYED", "UNDER_REVIEW")


def assert_hardware(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0
    assert data["category"] in ("LAPTOP", "DESKTOP", "SERVER", "MONITOR", "MOBILE")
    assert isinstance(data["physical_cores"], int) and data["physical_cores"] >= 0
    assert isinstance(data["purchase_cost_cents"], int) and data["purchase_cost_cents"] >= 0
    assert is_iso8601_timestamp(data["in_service_date"])
    assert isinstance(data["useful_life_months"], int) and data["useful_life_months"] >= 1
    assert isinstance(data["salvage_value_cents"], int) and data["salvage_value_cents"] >= 0
    assert data["status"] in ("IN_STOCK", "ASSIGNED", "IN_REPAIR", "RETIRED", "DISPOSED")
    assert data["support_status"] in ("IN_WARRANTY", "LEASED", "OUT_OF_WARRANTY", "UNCOVERED")
    assert isinstance(data["accumulated_depreciation_cents"], int)
    assert isinstance(data["net_book_value_cents"], int)
    assert isinstance(data["disposal_proceeds_cents"], int)
    assert isinstance(data["disposal_gain_loss_cents"], int)


def assert_hardware_book_invariants(data: dict):
    """Book-value invariants that must hold on any hardware read (PRD Section 2.6, 3.2)."""
    assert data["net_book_value_cents"] >= data["salvage_value_cents"], (
        "net_book_value_cents must never drop below salvage_value_cents"
    )
    assert data["accumulated_depreciation_cents"] <= (
        data["purchase_cost_cents"] - data["salvage_value_cents"]
    ), "accumulated depreciation must never exceed the depreciable base"
    assert (
        data["net_book_value_cents"]
        == data["purchase_cost_cents"] - data["accumulated_depreciation_cents"]
    ), "net_book_value_cents must equal purchase_cost - accumulated_depreciation"


def assert_coverage(data: dict):
    _assert_common(data)
    assert isinstance(data["hardware_asset_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert data["coverage_type"] in ("WARRANTY", "LEASE")
    assert is_iso8601_timestamp(data["coverage_start"])
    assert is_iso8601_timestamp(data["coverage_end"])
    assert isinstance(data["monthly_cost_cents"], int) and data["monthly_cost_cents"] >= 0
    assert isinstance(data["auto_renew"], bool)
    assert data["status"] in ("ACTIVE", "EXPIRED", "RENEWED", "CANCELLED")


def assert_entitlement(data: dict):
    _assert_common(data)
    assert isinstance(data["software_product_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["entitled_units"], int) and data["entitled_units"] >= 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert is_iso8601_timestamp(data["term_start"])
    assert is_iso8601_timestamp(data["term_end"])
    assert isinstance(data["grace_days"], int) and data["grace_days"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "RENEWED")
    assert isinstance(data["consumed_units"], int)
    assert isinstance(data["available_units"], int)
    assert data["available_units"] == data["entitled_units"] - data["consumed_units"], (
        "available_units must equal entitled_units - consumed_units"
    )


def assert_installation(data: dict):
    _assert_common(data)
    assert isinstance(data["software_product_id"], str)
    assert isinstance(data["hardware_asset_id"], str)
    assert isinstance(data["license_entitlement_id"], str)
    assert isinstance(data["required_core_units"], int)
    assert data["status"] in ("PENDING", "ACTIVE", "UNINSTALLED", "REJECTED")


def assert_checkout(data: dict):
    _assert_common(data)
    assert isinstance(data["hardware_asset_id"], str)
    assert isinstance(data["employee_id"], str)
    assert is_iso8601_timestamp(data["checkout_at"])
    assert is_iso8601_timestamp(data["expected_return_at"])
    assert data["status"] in ("OPEN", "RETURNED", "LOST")


def assert_disposal_request(data: dict):
    _assert_common(data)
    assert isinstance(data["hardware_asset_id"], str)
    assert isinstance(data["submitted_by_user_id"], str)
    assert data["reason"] in ("END_OF_LIFE", "DAMAGED", "LOST", "SOLD")
    assert isinstance(data["proposed_proceeds_cents"], int) and data["proposed_proceeds_cents"] >= 0
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "COMPLETED", "REVERSED")


def assert_renewal_order(data: dict):
    _assert_common(data)
    assert data["target_type"] in ("ENTITLEMENT", "COVERAGE")
    assert isinstance(data["extend_months"], int) and data["extend_months"] >= 1
    assert isinstance(data["quoted_cost_cents"], int)
    assert data["status"] in ("QUOTED", "COMPLETED", "CANCELLED")


def assert_true_up(data: dict):
    _assert_common(data)
    assert isinstance(data["software_product_id"], str)
    assert data["variant"] in ("LIVE", "AUDIT")
    assert isinstance(data["total_entitled_units"], int)
    assert isinstance(data["total_consumed_units"], int)
    assert isinstance(data["position_units"], int)
    assert data["verdict"] in ("COMPLIANT", "OVER_DEPLOYED")
    assert data["status"] in ("DRAFT", "FINALIZED")


def assert_finding(data: dict):
    """ComplianceFinding is immutable: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "finding id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["software_product_id"], str)
    assert isinstance(data["true_up_reconciliation_id"], str)
    assert isinstance(data["shortfall_units"], int) and data["shortfall_units"] >= 0
