"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Shared field checks
# ---------------------------------------------------------------------------

def _assert_top_level_common_fields(data: dict, entity: str):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer starting at 1"


def _assert_child_common_fields(data: dict, entity: str):
    """Sub-resources carry only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_customer(data: dict):
    _assert_top_level_common_fields(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["discount_pct"], (int, float))
    assert 0 <= data["discount_pct"] < 1
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["credit_holds_cents"], int)
    assert isinstance(data["available_credit_cents"], int)
    assert data["account_status"] in ("ACTIVE", "CREDIT_HOLD")


def assert_unit(data: dict):
    _assert_top_level_common_fields(data, "Unit")
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["model"], str) and data["model"]
    assert data["power_type"] in ("BATTERY", "LP")
    assert data["fuel_program"] in ("BATTERY", "LP")
    assert data["disposition"] in ("NEW_SALE", "RENTAL_FLEET", "USED_SALE")
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 1
    assert isinstance(data["weekly_rate_cents"], int)
    assert isinstance(data["monthly_rate_cents"], int)
    assert isinstance(data["pm_interval_hours"], int) and data["pm_interval_hours"] >= 1
    assert isinstance(data["hour_meter"], (int, float))
    assert isinstance(data["last_pm_hours"], (int, float))
    assert isinstance(data["next_pm_due_hours"], (int, float))
    assert data["maintenance_posture"] in ("PM_OK", "PM_DUE")
    assert data["availability_status"] in (
        "AVAILABLE", "ON_RENT", "IN_SHOP", "IN_RECON", "LISTED", "SOLD", "ON_LEASE")
    assert data.get("resale_price_cents") is None or \
        isinstance(data["resale_price_cents"], int)
    assert isinstance(data["utilization_pct_90d"], (int, float))


def assert_quote(data: dict):
    _assert_top_level_common_fields(data, "Quote")
    assert is_valid_uuid(data.get("customer_id", "")), "Quote.customer_id must be UUID"
    assert data["kind"] in ("NEW_CONFIG", "USED_UNIT_SALE")
    assert data.get("unit_id") is None or is_valid_uuid(data["unit_id"])
    assert isinstance(data["valid_until"], str) and data["valid_until"]
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "EXPIRED")
    assert data.get("submitted_at") is None or \
        is_iso8601_timestamp(data["submitted_at"])
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    for field in ("subtotal_cents", "discount_cents", "tax_cents", "total_cents"):
        assert isinstance(data[field], int), f"Quote.{field} must be integer cents"


def assert_quote_line(data: dict):
    _assert_child_common_fields(data, "QuoteLine")
    assert is_valid_uuid(data.get("quote_id", "")), "QuoteLine.quote_id must be UUID"
    assert isinstance(data["description"], str)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["extended_cents"], int)
    assert data["extended_cents"] == data["qty"] * data["unit_price_cents"], \
        "extended_cents must equal qty * unit_price_cents"


def assert_rental_contract(data: dict):
    _assert_top_level_common_fields(data, "RentalContract")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["scheduled_days"], int) and data["scheduled_days"] >= 1
    assert data["rate_tier"] in ("DAILY", "WEEKLY", "MONTHLY")
    assert isinstance(data["provisional_estimate_cents"], int)
    assert data.get("final_charge_cents") is None or \
        isinstance(data["final_charge_cents"], int)
    assert data.get("checkout_hours") is None or \
        isinstance(data["checkout_hours"], (int, float))
    assert data.get("return_hours") is None or \
        isinstance(data["return_hours"], (int, float))
    assert data.get("actual_return_date") is None or \
        isinstance(data["actual_return_date"], str)
    assert data["status"] in ("RESERVED", "ON_RENT", "RETURNED", "CANCELLED")


def assert_meter_reading(data: dict):
    _assert_child_common_fields(data, "MeterReading")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["reading_hours"], (int, float))


def assert_fuel_event(data: dict):
    _assert_child_common_fields(data, "FuelEvent")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data["event_type"] in ("CHARGE", "SWAP", "LP_REFILL")
    assert isinstance(data["cost_cents"], int)


def assert_service_call(data: dict):
    _assert_top_level_common_fields(data, "ServiceCall")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["call_type"] in ("BREAKDOWN", "PM")
    assert data["priority"] in ("EMERGENCY", "STANDARD")
    assert data.get("operator_id") is None or is_valid_uuid(data["operator_id"])
    assert data.get("technician_id") is None or is_valid_uuid(data["technician_id"])
    assert isinstance(data["required_parts"], list)
    assert data.get("used_parts") is None or isinstance(data["used_parts"], list)
    assert isinstance(data["auto_created"], bool)
    assert data["status"] in ("OPEN", "DISPATCHED", "CLOSED")


def assert_technician(data: dict):
    _assert_top_level_common_fields(data, "Technician")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_branch"], str) and data["home_branch"]
    assert isinstance(data["van_stock"], list)
    for entry in data["van_stock"]:
        assert isinstance(entry["part_number"], str)
        assert isinstance(entry["qty"], int) and entry["qty"] >= 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_operator(data: dict):
    _assert_top_level_common_fields(data, "Operator")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["badge_number"], str) and data["badge_number"]


def assert_certification(data: dict):
    _assert_top_level_common_fields(data, "Certification")
    assert is_valid_uuid(data.get("operator_id", ""))
    assert data["cert_class"] in ("SIT_DOWN", "STAND_UP", "ORDER_PICKER")
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert isinstance(data["expires_at"], str) and data["expires_at"]
    assert isinstance(data["renewed_count"], int) and data["renewed_count"] >= 0
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_lease_contract(data: dict):
    _assert_top_level_common_fields(data, "LeaseContract")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["allowed_hours"], int) and data["allowed_hours"] >= 0
    assert isinstance(data["excess_hour_rate_cents"], int)
    assert isinstance(data["residual_value_cents"], int)
    assert data.get("return_date") is None or isinstance(data["return_date"], str)
    assert data.get("settlement_total_cents") is None or \
        isinstance(data["settlement_total_cents"], int)
    assert data["status"] in ("ACTIVE", "RETURNED", "SETTLED")


def assert_lease_inspection(data: dict):
    _assert_child_common_fields(data, "LeaseInspection")
    assert is_valid_uuid(data.get("lease_id", ""))
    assert data["condition_grade"] in ("A", "B", "C", "D")
    assert isinstance(data["hours_at_return"], (int, float))
    assert isinstance(data["appraised_value_cents"], int)
    assert isinstance(data["wear_charge_cents"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED")


def assert_reconditioning_order(data: dict):
    _assert_top_level_common_fields(data, "ReconditioningOrder")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["qc_fail_count"], int) and data["qc_fail_count"] >= 0
    assert data.get("listing_price_cents") is None or \
        isinstance(data["listing_price_cents"], int)
    assert data["status"] in ("IN_PROGRESS", "COMPLETED")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_customer_credit_invariant(customer: dict):
    """available == credit_limit - outstanding - holds (PRD §2.10)."""
    expected = (customer["credit_limit_cents"]
                - customer["outstanding_balance_cents"]
                - customer["credit_holds_cents"])
    assert customer["available_credit_cents"] == expected, (
        f"available_credit_cents {customer['available_credit_cents']} != "
        f"limit {customer['credit_limit_cents']} - outstanding "
        f"{customer['outstanding_balance_cents']} - holds "
        f"{customer['credit_holds_cents']}")


def van_stock_qty(technician: dict, part_number: str) -> int:
    """Return the van-stock quantity for a part (0 when the entry is absent)."""
    for entry in technician.get("van_stock", []):
        if entry["part_number"] == part_number:
            return entry["qty"]
    return 0
