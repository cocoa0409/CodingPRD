"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("PLANNING", "IN_FIELD", "CLOSED")
    assert data["default_language"] in ("EN", "ES", "ZH", "VI")
    assert isinstance(data["supported_languages"], list) and len(data["supported_languages"]) >= 1


def assert_area(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "IN_FIELD", "FROZEN", "COMPLETE")
    assert data["budget_committed_cents"] >= 0
    assert data["budget_remaining_cents"] == data["budget_cents"] - data["budget_committed_cents"]


def assert_enumerator(data: dict):
    _assert_common(data)
    assert data["status"] in ("APPLICANT", "HIRED", "ACTIVE", "SUSPENDED")
    assert isinstance(data["languages"], list) and len(data["languages"]) >= 1
    assert isinstance(data["fraud_flag"], bool)
    assert data["net_pay_cents"] == data["gross_pay_cents"] - data["reversed_pay_cents"]


def assert_case(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "UNASSIGNED", "ASSIGNED", "IN_PROGRESS", "COMPLETE",
        "REFUSED", "VACANT", "MAX_ATTEMPTS",
    )
    assert data["attempt_count"] >= 0


def assert_case_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "RELEASED")


def assert_attempt(data: dict):
    _assert_common(data)
    assert data["mode"] in ("IN_PERSON", "PHONE")
    assert data["status"] in ("LOGGED", "CANCELLED")
    assert data["pay_committed_cents"] >= 0


def assert_response(data: dict):
    _assert_common(data)
    assert data["mode"] in ("IN_PERSON", "PHONE")
    assert data["status"] in ("CAPTURED", "ACCEPTED", "INVALIDATED")
    assert 0 <= data["fraud_score"] <= 100
    assert isinstance(data["needs_reinterview"], bool)


def assert_reinterview(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "IN_REVIEW", "CONFIRMED", "DISCREPANT", "FRAUD")


def assert_pay_period(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "LOCKED", "PAID")
    assert data["provisional_total_cents"] >= 0


def assert_pay_line(data: dict):
    _assert_common(data)
    assert data["line_type"] in ("STIPEND", "MILEAGE", "BONUS")
    assert data["status"] in ("ACCRUED", "REVERSED")
    assert data["amount_cents"] > 0


def assert_area_count_partition(data: dict):
    """PRD §3.2 partition: the per-status counts sum to total_case_count."""
    partition = (
        data["pending_case_count"]
        + data["in_progress_case_count"]
        + data["complete_case_count"]
        + data["refused_case_count"]
        + data["vacant_case_count"]
        + data["max_attempts_case_count"]
    )
    assert partition == data["total_case_count"], (
        f"case-count partition {partition} must equal total_case_count "
        f"{data['total_case_count']}"
    )
