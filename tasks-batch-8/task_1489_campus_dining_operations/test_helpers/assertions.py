"""Entity assertions and domain invariant checkers."""
import re
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_ISO8601_MILLIS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_millis_timestamp(value: str, field: str = "timestamp"):
    """PRD: created_at/updated_at are ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str) and _ISO8601_MILLIS_RE.match(value), (
        f"{field} must be an ISO 8601 UTC timestamp with three fractional digits, "
        f"got {value!r}"
    )


def assert_instant_equal(actual: str, expected: str):
    """Compare two logical-clock-stamped instants by value, not string shape."""
    def _parse(v):
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    assert is_iso8601_timestamp(actual), f"{actual!r} is not an ISO 8601 UTC timestamp"
    assert _parse(actual) == _parse(expected), f"{actual!r} != {expected!r} as instants"


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_dining_hall(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["service_model"] in ["BOARD", "RETAIL", "HYBRID"]
    assert isinstance(data["dining_capacity"], int) and data["dining_capacity"] > 0
    assert isinstance(data["catering_kitchen_capacity"], int) \
        and data["catering_kitchen_capacity"] > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_vendor_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dining_hall_id", "")), "dining_hall_id must be a UUID"
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["board_rate_per_cover_cents"], int) \
        and data["board_rate_per_cover_cents"] >= 0
    assert 0 <= data["retail_commission_bps"] <= 10000
    assert 0 <= data["catering_commission_bps"] <= 10000
    assert isinstance(data["minimum_monthly_guarantee_cents"], int) \
        and data["minimum_monthly_guarantee_cents"] >= 0
    assert isinstance(data["effective_start_date"], str)
    assert isinstance(data["effective_end_date"], str)
    assert data["status"] in ["NEGOTIATION", "ACTIVE", "EXPIRED", "TERMINATED"]


def assert_menu_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dining_hall_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert 1 <= data["cycle_length_weeks"] <= 8
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ["DRAFT", "PUBLISHED", "ARCHIVED"]


def assert_recipe(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dining_hall_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert data["station"] in ["GRILL", "DELI", "PIZZA", "SALAD", "GLOBAL", "BAKERY"]
    assert isinstance(data["allergen_tags"], list)
    assert isinstance(data["dietary_flags"], list)
    assert 0 < data["popularity_share"] <= 1
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] > 0
    assert isinstance(data["allergen_reviewed"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_meal_period(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dining_hall_id", ""))
    assert is_valid_uuid(data.get("menu_cycle_id", ""))
    assert isinstance(data["service_date"], str)
    assert data["meal_period"] in ["BREAKFAST", "LUNCH", "DINNER", "LATE_NIGHT"]
    assert data["status"] in [
        "SCHEDULED", "FORECAST_LOCKED", "IN_SERVICE", "RECONCILED", "CLOSED", "CANCELLED",
    ]
    for field in ("forecasted_covers", "actual_board_swipes",
                  "actual_retail_sales_cents", "actual_covers"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["forecast_variance_pct"] is None or isinstance(
        data["forecast_variance_pct"], (int, float))
    assert isinstance(data["posted_waste_kg"], (int, float))
    assert isinstance(data["landfill_waste_kg"], (int, float))
    assert data["diversion_rate"] is None or isinstance(data["diversion_rate"], (int, float))
    assert isinstance(data["sustainability_alert"], bool)


def assert_swipe_event(data: dict):
    """Append-only record: id + created_at from the common set, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "SwipeEvent must not carry updated_at"
    assert "version" not in data, "SwipeEvent must not carry version"
    assert is_valid_uuid(data.get("meal_period_id", ""))
    assert data["entry_type"] in ["BOARD_SWIPE", "RETAIL_SALE"]
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data.get("recorded_at", ""))


def assert_production_forecast(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("meal_period_id", ""))
    assert is_valid_uuid(data.get("recipe_id", ""))
    assert data["variant"] in ["BASE", "TREND"]
    assert isinstance(data["forecasted_portions"], int)
    assert isinstance(data["base_covers"], int)
    assert data["status"] in ["DRAFT", "LOCKED", "SUPERSEDED"]


def assert_accommodation_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dining_hall_id", ""))
    assert isinstance(data["student_ref"], str) and data["student_ref"]
    assert isinstance(data["allergen_exclusions"], list)
    assert data["dietary_requirement"] in [
        "VEGAN", "VEGETARIAN", "HALAL", "KOSHER", "GLUTEN_FREE", "OTHER",
    ]
    assert isinstance(data["review_notes"], str)
    assert data["status"] in [
        "SUBMITTED", "NUTRITION_REVIEW", "APPROVED", "ACTIVE", "CANCELLED",
    ]


def assert_labor_shift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dining_hall_id", ""))
    assert data["staff_ref"] is None or isinstance(data["staff_ref"], str)
    assert data["role"] in ["COOK", "SERVER", "CASHIER", "DISHWASHER"]
    assert isinstance(data["shift_date"], str)
    assert 0 <= data["start_minute"] <= 1439
    assert data["start_minute"] < data["end_minute"] <= 1440
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert data["status"] in ["PLANNED", "ASSIGNED", "CONFIRMED", "COMPLETED", "NO_SHOW"]
    assert data["worked_minutes"] is None or isinstance(data["worked_minutes"], int)
    for field in ("regular_minutes", "overtime_minutes",
                  "regular_pay_cents", "overtime_pay_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_waste_log(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("meal_period_id", ""))
    assert data["category"] in ["PRE_CONSUMER", "POST_CONSUMER", "SPOILAGE"]
    assert data["disposition"] in ["LANDFILL", "COMPOST", "DONATION"]
    assert data["weight_kg"] > 0
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]
    assert data["verified_by_user_id"] is None or isinstance(
        data["verified_by_user_id"], str)
    assert data["status"] in ["RECORDED", "VERIFIED", "POSTED"]


def assert_inspection_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dining_hall_id", ""))
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    assert isinstance(data["inspection_date"], str)
    assert isinstance(data["violations"], list)
    assert data["score"] is None or isinstance(data["score"], int)
    assert data["outcome"] is None or data["outcome"] in ["PASS", "CONDITIONAL", "FAIL"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACKNOWLEDGED", "CLOSED"]


def assert_corrective_action(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("inspection_report_id", ""))
    assert isinstance(data["violation_code"], str) and data["violation_code"]
    assert data["severity"] in ["CRITICAL", "MAJOR", "MINOR"]
    assert isinstance(data["due_date"], str)
    assert data["status"] in ["OPEN", "OVERDUE", "RESOLVED", "VERIFIED"]
    assert data["resolved_by_user_id"] is None or isinstance(
        data["resolved_by_user_id"], str)
    assert data["verified_by_user_id"] is None or isinstance(
        data["verified_by_user_id"], str)


def assert_department(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["department_code"], str) and data["department_code"]
    assert isinstance(data["semester_budget_cents"], int) \
        and data["semester_budget_cents"] >= 0
    for field in ("reserved_cents", "committed_cents", "spent_cents", "available_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_catering_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("dining_hall_id", ""))
    assert is_valid_uuid(data.get("department_id", ""))
    assert data["revised_from_id"] is None or is_valid_uuid(data["revised_from_id"])
    assert isinstance(data["event_date"], str)
    assert data["time_slot"] in ["BREAKFAST", "LUNCH", "DINNER"]
    assert isinstance(data["guaranteed_covers"], int) and data["guaranteed_covers"] > 0
    assert isinstance(data["menu_lines"], list) and len(data["menu_lines"]) > 0
    assert isinstance(data["dietary_plates"], int) and data["dietary_plates"] >= 0
    assert isinstance(data["quoted_total_cents"], int)
    assert data["final_total_cents"] is None or isinstance(data["final_total_cents"], int)
    assert isinstance(data["cancellation_fee_cents"], int)
    assert data["approval_status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CANCELLED",
    ]
    assert data["fulfillment_status"] in [
        "NONE", "SCHEDULED", "FULFILLED", "INVOICED", "PAID", "CANCELLED",
    ]


def assert_commission_statement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("vendor_contract_id", ""))
    assert isinstance(data["period_month"], str)
    assert data["status"] in ["PROVISIONAL", "FINALIZED", "DISPUTED"]
    for field in ("board_revenue_cents", "retail_commission_cents",
                  "catering_commission_cents", "guarantee_top_up_cents",
                  "total_due_to_university_cents", "provisional_total_due_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["finalized_at"] is None or is_iso8601_timestamp(data["finalized_at"])


def assert_department_budget_conservation(dept: dict):
    """PRD: the four buckets sum exactly back to the semester budget at every instant."""
    total = (dept["available_cents"] + dept["reserved_cents"]
             + dept["committed_cents"] + dept["spent_cents"])
    assert total == dept["semester_budget_cents"], (
        f"Budget conservation violated: {dept['available_cents']} + "
        f"{dept['reserved_cents']} + {dept['committed_cents']} + {dept['spent_cents']} "
        f"!= {dept['semester_budget_cents']}"
    )
