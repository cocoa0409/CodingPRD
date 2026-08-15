"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

WORK_ORDER_STATES = [
    "INTAKE", "TEARDOWN", "QUOTE_DRAFT", "QUOTE_SENT", "REVISION_REQUESTED",
    "APPROVED", "IN_REPAIR", "ASSEMBLED", "TEST_PENDING", "TEST_PASSED",
    "CERTIFIED", "SCRAP_AUTHORIZED", "SCRAPPED", "EXCHANGE_SELECTED",
    "EXCHANGE_FULFILLED", "CLOSED", "CANCELLED",
]
QUOTE_STATES = ["DRAFT", "SENT", "APPROVED", "REVISION_REQUESTED", "EXPIRED", "SUPERSEDED", "REJECTED_SCRAP"]
RESERVATION_STATES = ["OPEN", "CONSUMED", "RELEASED"]
PRESSURE_TEST_STATES = ["SCHEDULED", "PASSED", "FAILED", "VOIDED", "CANCELLED"]
CERTIFICATE_STATES = ["ISSUED", "REVOKED"]
EXCHANGE_UNIT_STATES = ["IN_POOL", "RESERVED", "FULFILLED", "CORE_RECEIVED", "SETTLED"]
FIELD_JOB_STATES = ["REQUESTED", "SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED"]


def assert_common_fields(data: dict):
    """PRD §2.4: id is a UUID without type prefix; created_at/updated_at are
    ISO 8601 UTC; version starts at 1 and increments."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_shop(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["labor_rate_cents_per_hour"], int)
    assert isinstance(data["kerf_mm"], int)
    assert isinstance(data["min_remnant_mm"], int)


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["ytd_spend_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_technician(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["skills"], list) and len(data["skills"]) > 0
    assert isinstance(data["active"], bool)


def assert_seal_kit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["kit_code"], str) and data["kit_code"]
    assert data["bore_min_mm"] <= data["bore_max_mm"]
    assert data["pressure_class_max"] in ("CLASS_3000", "CLASS_5000")
    assert isinstance(data["price_cents"], int)


def assert_cylinder(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["pressure_class"] in ("CLASS_3000", "CLASS_5000")
    assert data["fluid_type"] in ("MINERAL_OIL", "PHOSPHATE_ESTER", "WATER_GLYCOL")
    assert data["status"] in ("ACTIVE", "RETIRED", "EXCHANGED")


def assert_work_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["cylinder_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["tier"] in ("STANDARD", "EXPEDITE", "EMERGENCY")
    assert isinstance(data["promised_hours"], int)
    assert data["status"] in WORK_ORDER_STATES


def assert_teardown_report(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert isinstance(data["rod_needed"], bool)
    assert isinstance(data["tube_needed"], bool)
    assert isinstance(data["estimated_labor_hours"], (int, float))


def assert_quote(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["teardown_report_id"])
    assert isinstance(data["pinned_teardown_version"], int)
    assert data["tier_snapshot"] in ("STANDARD", "EXPEDITE", "EMERGENCY")
    assert data["status"] in QUOTE_STATES
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["line_items"], list)
    for line in data["line_items"]:
        assert line["kind"] in ("SEAL_KIT", "ROD", "TUBE", "HONING", "LABOR", "SUPPLIES")
        assert isinstance(line["amount_cents"], int)


def get_line_amount(quote_data: dict, kind: str) -> int:
    """Return the amount_cents of the quote line of the given kind."""
    amounts = [line["amount_cents"] for line in quote_data["line_items"] if line["kind"] == kind]
    assert len(amounts) == 1, f"expected exactly one {kind} line, got {amounts}"
    return amounts[0]


def assert_inventory_item(data: dict):
    assert_common_fields(data)
    assert data["material"] in ("CHROME_ROD", "HONING_TUBE")
    assert isinstance(data["length_mm"], int) and data["length_mm"] >= 0
    assert isinstance(data["cost_per_mm_cents"], int)
    assert data["status"] in ("AVAILABLE", "DEPLETED")
    assert data["origin"] in ("RECEIVED", "REMNANT")


def assert_stock_reservation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert data["material"] in ("CHROME_ROD", "HONING_TUBE")
    assert isinstance(data["cut_length_mm"], int)
    assert isinstance(data["kerf_mm"], int)
    assert data["status"] in RESERVATION_STATES


def assert_pressure_test(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["test_bay_id"])
    assert isinstance(data["required_hold_psi"], int)
    assert data["status"] in PRESSURE_TEST_STATES


def assert_certificate(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert isinstance(data["issued_by"], str) and data["issued_by"]
    assert data["status"] in CERTIFICATE_STATES


def assert_exchange_unit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["bore_mm"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert data["status"] in EXCHANGE_UNIT_STATES


def assert_field_service_job(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["distance_km"], int)
    assert isinstance(data["assemblies"], list)
    assert isinstance(data["provisional_price_cents"], int)
    assert data["status"] in FIELD_JOB_STATES
