"""Entity assertions and domain invariant checkers for the Flooring API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CATEGORIES = ["HARDWOOD", "LVP", "TILE", "CARPET"]


def assert_common_system_fields(data: dict):
    """id (UUID), created_at/updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_registration_fields(data: dict):
    """Customer/SalesRep: id + created_at only; no version, no updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "registration records carry no version field"
    assert "updated_at" not in data, "registration records carry no updated_at field"


def assert_product(data: dict):
    assert_common_system_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert data["category"] in CATEGORIES
    assert isinstance(data["material_cost_per_sqft_cents"], int) and data["material_cost_per_sqft_cents"] >= 1
    assert isinstance(data["labor_rate_per_sqft_cents"], int) and data["labor_rate_per_sqft_cents"] >= 1
    assert isinstance(data["requires_underlayment"], bool)
    assert isinstance(data["underlayment_cost_per_sqft_cents"], int)
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert isinstance(data["warranty_years"], int) and data["warranty_years"] >= 0
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_job(data: dict):
    assert_common_system_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["sales_rep_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["declared_sqft"], (int, float)) and data["declared_sqft"] > 0
    assert data["status"] in [
        "DRAFT", "MEASURED", "RE_MEASURE", "ESTIMATED",
        "ACCEPTED", "IN_INSTALL", "COMPLETED", "CANCELLED",
    ]


def assert_estimate(data: dict):
    assert_common_system_fields(data)
    assert isinstance(data["job_id"], str)
    assert data["variant"] in ["PROVISIONAL", "MEASURED"]
    assert isinstance(data["billable_sqft"], (int, float))
    assert isinstance(data["material_cost_cents"], int)
    assert isinstance(data["underlayment_cost_cents"], int)
    assert isinstance(data["labor_cost_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ["DRAFT", "ISSUED", "ACCEPTED", "EXPIRED", "VOIDED"]
    assert is_iso8601_timestamp(data.get("valid_until", "")), "valid_until must be ISO 8601"


def assert_estimate_total_consistent(data: dict):
    """total_cents is the sum of the rounded material, underlayment, and labor lines."""
    expected = data["material_cost_cents"] + data["underlayment_cost_cents"] + data["labor_cost_cents"]
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} must equal sum of lines {expected}"
    )


def assert_material_order(data: dict):
    assert_common_system_fields(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["order_sqft"], (int, float))
    assert isinstance(data["lead_time_days"], int)
    assert is_iso8601_timestamp(data.get("expected_ready_date", "")), "expected_ready_date must be ISO 8601"
    assert data["status"] in ["ORDERED", "BACKORDERED", "RECEIVED", "CANCELLED"]
    assert isinstance(data["backorder_count"], int) and data["backorder_count"] >= 0


def assert_install_crew(data: dict):
    assert_common_system_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["skill_categories"], list) and len(data["skill_categories"]) >= 1
    for cat in data["skill_categories"]:
        assert cat in CATEGORIES
    assert isinstance(data["daily_sqft_capacity"], int) and data["daily_sqft_capacity"] > 0
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert data["status"] in ["AVAILABLE", "INACTIVE"]


def assert_install_slot(data: dict):
    assert_common_system_fields(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["crew_id"], str)
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"
    assert isinstance(data["scheduled_sqft"], (int, float))
    assert data["status"] in ["SCHEDULED", "CANCELLED", "DONE"]


def assert_warranty_claim(data: dict):
    assert_common_system_fields(data)
    assert isinstance(data["job_id"], str)
    assert is_iso8601_timestamp(data.get("filed_at", "")), "filed_at must be ISO 8601"
    assert isinstance(data["defect_description"], str)
    assert data["status"] in ["FILED", "APPROVED", "DENIED"]
