"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def date_part(value) -> str:
    """Normalize an ISO date or datetime string to its YYYY-MM-DD date part.

    The PRD specifies whole-ISO-date arithmetic (§2.7) and date-stamped fields
    such as due_date / fulfilled_on / filed_on (§3); comparing the date part
    keeps assertions faithful whether the server serializes a bare date or a
    midnight datetime.
    """
    assert isinstance(value, str), f"Expected an ISO date/datetime string, got {value!r}"
    return value[:10]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("case_number"), str) and data["case_number"]
    assert isinstance(data.get("agency_affiliate_code"), str)
    assert isinstance(data.get("household_size"), int) and data["household_size"] >= 1
    assert isinstance(data.get("scheduled_arrival_date"), str)
    assert data.get("status") in ("PRE_ARRIVAL", "ARRIVED", "TRANSFERRED_OUT")
    assert data.get("posture") in ("ON_TRACK", "AT_RISK", "OVERDUE")
    assert isinstance(data.get("topics_completed"), list)
    assert isinstance(data.get("airport_pickup_completed"), bool)


def assert_household_member(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    assert data.get("relationship") in ("PRINCIPAL", "SPOUSE", "CHILD", "OTHER_RELATIVE")
    assert isinstance(data.get("work_eligible"), bool)


def assert_housing_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("address"), str) and data["address"]
    assert isinstance(data.get("bedrooms"), int) and data["bedrooms"] >= 0
    assert data.get("status") in ("AVAILABLE", "RESERVED", "OCCUPIED")


def assert_housing_setup(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("housing_unit_id", ""))
    assert isinstance(data.get("occupancy_start"), str)
    assert isinstance(data.get("occupancy_end"), str)
    assert isinstance(data.get("furnishing_items_completed"), list)
    assert data.get("status") in ("PREPARING", "READY", "OCCUPIED", "VACATED")


def assert_service_benchmark(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data.get("service_type") in (
        "HOME_VISIT", "HEALTH_SCREENING", "SSN_APPLICATION", "BENEFITS_ENROLLMENT",
        "SCHOOL_ENROLLMENT", "EMPLOYMENT_PLAN", "CULTURAL_ORIENTATION",
    )
    assert data.get("due_rule") in ("DAYS_30", "DAYS_90")
    assert isinstance(data.get("planned_due_date"), str)
    assert isinstance(data.get("due_date"), str)
    assert data.get("status") in ("PENDING", "MET", "WAIVED")


def assert_benefit_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data.get("benefit_type") in (
        "SSN", "STATE_ID", "CASH_ASSISTANCE", "MEDICAL", "FOOD_ASSISTANCE",
    )
    assert data.get("status") in (
        "DRAFT", "FILED", "APPROVED", "DENIED", "APPEALED", "WITHDRAWN",
    )


def assert_employment_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data.get("monthly_income_cents"), int)
    assert isinstance(data.get("trailing_3m_income_cents"), int)
    assert isinstance(data.get("employed_members_count"), int)
    assert data.get("status") in ("ACTIVE", "CERTIFIED", "SUPERSEDED", "CLOSED_TRANSFERRED")


def assert_orientation_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data.get("topic") in (
        "US_LAWS", "HEALTHCARE_ACCESS", "EDUCATION_SYSTEM",
        "EMPLOYMENT_RIGHTS", "HOUSING_SAFETY", "BUDGETING",
    )
    assert isinstance(data.get("start_at"), str)
    assert isinstance(data.get("end_at"), str)
    assert data.get("status") in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_case_note(data: dict):
    """Append-only documentation (PRD §2.4): id + created_at, and both
    updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("case_id", ""))
    assert data.get("note_type") in ("GENERAL", "SERVICE_DELIVERY", "INCIDENT", "TRANSFER")
    assert isinstance(data.get("body"), str)
    assert data.get("author_role") in (
        "CASE_MANAGER", "HOUSING_COORDINATOR", "EMPLOYMENT_SPECIALIST", "AGENCY_DIRECTOR",
    )
    assert "updated_at" not in data, "CaseNote is append-only: no updated_at"
    assert "version" not in data, "CaseNote is append-only: no version"


def assert_case_transfer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data.get("receiving_affiliate_code"), str)
    assert data.get("reason") in (
        "SECONDARY_MIGRATION", "FAMILY_REUNIFICATION", "EMPLOYMENT_OPPORTUNITY",
    )
    assert data.get("status") in ("INITIATED", "COMPLETED", "REJECTED", "WITHDRAWN")


def assert_federal_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    for field in (
        "cases_arrived_count", "benchmarks_met_count", "benchmarks_met_on_time_count",
        "benchmarks_pending_count", "benchmarks_waived_count",
        "per_capita_allocation_cents", "revision_count",
    ):
        assert isinstance(data.get(field), int), f"{field} must be an integer"
    assert data.get("status") in ("DRAFT", "SUBMITTED", "ACCEPTED")


def assert_benchmark_partition(benchmarks: list, expected_total: int):
    """Per-case benchmark status partition: every seeded benchmark is exactly
    one of PENDING / MET / WAIVED, and the partition total is conserved."""
    counts = {"PENDING": 0, "MET": 0, "WAIVED": 0}
    for bm in benchmarks:
        counts[bm["status"]] += 1
    total = sum(counts.values())
    assert total == expected_total, (
        f"Benchmark partition total {total} != expected {expected_total}: {counts}"
    )
    return counts
