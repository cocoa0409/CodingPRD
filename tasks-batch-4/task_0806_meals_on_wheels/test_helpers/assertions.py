"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    """id + created_at + updated_at + version for a mutable (versioned) resource."""
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_client(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["enrollment_status"] in (
        "INTAKE", "ASSESSED", "ACTIVE", "ON_HOLD", "DISCHARGED"
    )
    assert isinstance(data["oaa_eligible"], bool)
    assert data["income_tier"] in ("TIER_A", "TIER_B", "TIER_C")
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["monthly_income_cents"], int) and data["monthly_income_cents"] >= 0
    assert isinstance(data["suggested_contribution_cents"], int)
    assert isinstance(data["donation_balance_cents"], int)
    assert isinstance(data["lifetime_oaa_units"], int)
    assert isinstance(data["consecutive_no_answer"], int)


def assert_assessment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert 0 <= data["nutrition_determine_points"] <= 21
    assert data["nutrition_risk_category"] in ("GOOD", "MODERATE", "HIGH")
    assert 0 <= data["adl_score"] <= 6
    assert data["functional_level"] in ("INDEPENDENT", "PARTIAL", "DEPENDENT")
    assert isinstance(data["therapeutic_diet_required"], bool)
    assert data["therapeutic_diet_type"] in ("NONE", "RENAL", "DIABETIC", "LOW_SODIUM", "PUREED")
    assert 1 <= data["recommended_meals_per_day"] <= 3
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")


def assert_meal_plan(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("assessment_id", ""))
    assert is_valid_uuid(data.get("route_id", ""))
    assert data["meal_type"] in ("FROZEN", "HOT", "THERAPEUTIC")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CANCELLED")
    assert 1 <= data["meals_per_day"] <= 3
    assert isinstance(data["delivery_days"], list) and len(data["delivery_days"]) >= 1
    assert isinstance(data["weekly_meal_count"], int) and data["weekly_meal_count"] >= 1
    assert isinstance(data["suggested_contribution_per_meal_cents"], int)


def assert_route(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["zone"], str)
    assert isinstance(data["service_days"], list) and len(data["service_days"]) >= 1
    assert isinstance(data["max_meals_per_run"], int) and data["max_meals_per_run"] >= 1
    assert data["status"] in ("DRAFT", "ACTIVE")


def assert_driver(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("PENDING", "ACTIVE")


def assert_delivery(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("meal_plan_id", ""))
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("route_id", ""))
    assert data["meal_type"] in ("FROZEN", "HOT", "THERAPEUTIC")
    assert isinstance(data["meal_count"], int) and data["meal_count"] >= 1
    assert isinstance(data["oaa_units_accrued"], int)
    assert data["status"] in (
        "SCHEDULED", "DELIVERED", "NO_ANSWER", "SKIPPED", "CANCELLED", "VOIDED"
    )


def assert_wellness_check(data: dict):
    """WellnessCheck is an immutable event record: id + created_at only —
    no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "WellnessCheck must NOT carry a version field"
    assert "updated_at" not in data, "WellnessCheck must NOT carry an updated_at field"
    assert data["outcome"] in ("OK", "NO_ANSWER")
    assert is_valid_uuid(data.get("delivery_id", ""))
    assert is_valid_uuid(data.get("client_id", ""))


def assert_welfare_alert(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert data["severity"] in ("LOW", "HIGH")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED", "RESOLVED")


def assert_contribution(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["period_month"], str)
    assert data["status"] in ("RECORDED", "VOIDED")


def assert_vacation_hold(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("ACTIVE", "COMPLETED", "CANCELLED")
