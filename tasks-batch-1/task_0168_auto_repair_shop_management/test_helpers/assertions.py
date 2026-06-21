"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """Common fields carried by every entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 (PRD §2.4)"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["phone"], str)
    assert isinstance(data["email"], str)


def assert_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["vin"], str) and data["vin"]
    assert isinstance(data["model_year"], int)
    assert isinstance(data["odometer_miles"], int)
    assert data["odometer_miles"] >= 0, "odometer_miles is non-negative (PRD §3.1)"


def assert_technician(data: dict):
    _assert_common(data)
    assert data["skill_level"] in ("A", "B", "C")
    assert isinstance(data["banked_flat_hours"], (int, float))
    assert isinstance(data["banked_actual_hours"], (int, float))
    # efficiency_pct may be null (PRD §3.7 boundary rule).
    assert data["efficiency_pct"] is None or isinstance(data["efficiency_pct"], (int, float))


def assert_service_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["bay_name"], str) and data["bay_name"]
    assert data["bay_type"] in ("GENERAL", "ALIGNMENT", "LIFT")


def assert_labor_operation(data: dict):
    _assert_common(data)
    assert isinstance(data["op_code"], str) and data["op_code"]
    assert data["book_hours"] > 0, "book_hours must be > 0 (PRD §3.1)"
    assert data["default_rate_cents"] > 0, "default_rate_cents must be > 0 (PRD §3.1)"


def assert_markup_tier(data: dict):
    _assert_common(data)
    assert isinstance(data["tier_index"], int) and data["tier_index"] >= 0
    assert isinstance(data["lower_bound_cents"], int) and data["lower_bound_cents"] >= 0
    assert data["upper_bound_cents"] is None or isinstance(data["upper_bound_cents"], int)
    assert isinstance(data["markup_pct"], (int, float)) and data["markup_pct"] >= 0


def assert_repair_order(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "ESTIMATE", "APPROVED", "IN_PROGRESS", "ON_HOLD",
        "COMPLETED", "INVOICED", "CLOSED", "CANCELLED",
    )
    for field in (
        "labor_total_cents", "parts_total_cents", "core_deposit_total_cents",
        "tax_cents", "grand_total_cents", "approved_work_value_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["is_comeback"], bool)


def assert_labor_line(data: dict):
    _assert_common(data)
    assert data["status"] in ("NOT_STARTED", "IN_PROGRESS", "PAUSED", "COMPLETED")
    assert data["billing_method"] in ("FLAT_RATE", "TIME_AND_MATERIALS")
    assert isinstance(data["book_hours"], (int, float))
    assert isinstance(data["actual_hours"], (int, float))
    assert isinstance(data["charge_cents"], int)
    assert isinstance(data["is_warranty"], bool)


def assert_part_line(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUOTED", "INSTALLED", "RETURNED")
    assert data["markup_mode"] in ("MARGINAL", "FLAT_BRACKET")
    assert data["quantity"] > 0, "quantity must be > 0 (PRD §3.5)"
    assert data["unit_cost_cents"] >= 0
    assert isinstance(data["extended_charge_cents"], int)
    assert isinstance(data["has_core"], bool)


def assert_core_charge(data: dict):
    _assert_common(data)
    assert data["status"] in ("CHARGED", "CORE_RETURNED", "FORFEITED")
    assert isinstance(data["deposit_cents"], int)
    assert isinstance(data["refunded_cents"], int)


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "REVIEWED")
    assert data["worst_severity"] in ("GREEN", "YELLOW", "RED")
    assert isinstance(data["red_item_count"], int)


def assert_recommended_job(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "DECLINED", "DEFERRED")
    assert data["severity"] in ("YELLOW", "RED")
    assert isinstance(data["estimated_value_cents"], int)


def assert_repair_order_total_consistency(data: dict):
    """PRD §3.6: grand_total = labor + parts + core_deposit + tax."""
    expected = (
        data["labor_total_cents"]
        + data["parts_total_cents"]
        + data["core_deposit_total_cents"]
        + data["tax_cents"]
    )
    assert data["grand_total_cents"] == expected, (
        f"grand_total_cents {data['grand_total_cents']} != "
        f"labor+parts+core+tax {expected} (PRD §3.6)"
    )
