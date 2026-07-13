"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _has_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _has_lightweight_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lightweight record must not carry updated_at"
    assert "version" not in data, "lightweight record must not carry version"


def assert_garden(data: dict):
    _has_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["total_plots"], int)
    assert isinstance(data["available_plot_count"], int)


def assert_plot(data: dict):
    _has_common_fields(data)
    assert data["size"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["status"] in ("AVAILABLE", "RESERVED", "ASSIGNED")


def assert_gardener(data: dict):
    _has_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["standing"] in ("GOOD", "PROBATION", "SUSPENDED")
    assert isinstance(data["tenure_seasons"], int)
    assert isinstance(data["strike_count"], int)
    assert isinstance(data["balance_owed_cents"], int)


def assert_application(data: dict):
    _has_common_fields(data)
    assert data["requested_size"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["status"] in (
        "SUBMITTED", "WAITLISTED", "OFFERED", "ACCEPTED", "DECLINED", "EXPIRED",
    )


def assert_assignment(data: dict):
    _has_common_fields(data)
    assert data["size"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["occupancy_status"] in (
        "ACTIVE", "RENEWAL_PENDING", "RENEWED", "ENDED", "FORFEITED",
    )
    assert data["fee_status"] in ("UNPAID", "PAID", "WAIVED", "REFUNDED")
    assert isinstance(data["provisional_fee_cents"], int)


def assert_compliance_case(data: dict):
    _has_common_fields(data)
    assert data["status"] in ("OPEN", "WARNED", "CURED", "ESCALATED")
    assert data["violation_type"] in (
        "NEGLECT", "RULE_BREACH", "UNPAID_FEE", "WATER_ABUSE",
    )


def assert_tool(data: dict):
    _has_common_fields(data)
    assert data["category"] in ("HAND", "POWER", "CART")


def assert_tool_loan(data: dict):
    _has_common_fields(data)
    assert data["status"] in ("CHECKED_OUT", "RETURNED", "RETURNED_LATE")
    assert isinstance(data["late_fine_cents"], int)


def assert_work_log(data: dict):
    _has_lightweight_fields(data)


def assert_water_reading(data: dict):
    _has_lightweight_fields(data)


def assert_shed_booking(data: dict):
    _has_lightweight_fields(data)
