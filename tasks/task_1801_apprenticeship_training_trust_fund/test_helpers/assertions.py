"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AllocationStatus,
    ClaimStatus,
    ClassStatus,
    EmployerStatus,
    EnrollmentStatus,
    FundPosture,
    PayBasis,
    ProgramStatus,
    PurchaseStatus,
    RegistrationAgency,
    RegistrationStatus,
    ReportStatus,
)


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict):
    """Every primary resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_trust_fund(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["posture"] in _enum_values(FundPosture)
    for field in (
        "contributions_received_cents",
        "disbursed_cents",
        "allocated_remaining_cents",
        "available_cents",
        "delinquent_employer_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_trust_fund_ledger(data: dict):
    """PRD §2.6: available = contributions received - disbursed - allocated remaining."""
    assert_trust_fund(data)
    expected = (
        data["contributions_received_cents"]
        - data["disbursed_cents"]
        - data["allocated_remaining_cents"]
    )
    assert data["available_cents"] == expected, (
        f"available_cents {data['available_cents']} != received "
        f"{data['contributions_received_cents']} - disbursed "
        f"{data['disbursed_cents']} - allocated {data['allocated_remaining_cents']}"
    )


def assert_employer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["agreement_rate_cents_per_hour"], int)
    assert data["status"] in _enum_values(EmployerStatus)
    assert isinstance(data["outstanding_cents"], int)


def assert_apprentice(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["trade"], str) and data["trade"]
    assert isinstance(data["journeyman_base_rate_cents"], int)
    assert data["program_status"] in _enum_values(ProgramStatus)
    assert data["registration_status"] in _enum_values(RegistrationStatus)
    assert data["registration_agency"] is None or data[
        "registration_agency"
    ] in _enum_values(RegistrationAgency)
    assert isinstance(data["ojt_hours_accumulated"], (int, float))
    assert isinstance(data["rti_credits_accumulated"], int)
    assert data["current_wage_step"] in (1, 2, 3, 4, 5)
    assert isinstance(data["current_wage_rate_cents"], int)


def assert_contribution_report(data: dict):
    assert_common_fields(data)
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int)
    assert 1 <= data["period_month"] <= 12
    assert isinstance(data["lines"], list)
    assert is_iso8601_timestamp(data.get("due_date", "")), (
        "due_date must be an ISO 8601 timestamp"
    )
    assert isinstance(data["provisional_due_cents"], int)
    assert data["contribution_due_cents"] is None or isinstance(
        data["contribution_due_cents"], int
    )
    assert data["flag_reason"] is None or isinstance(data["flag_reason"], str)
    assert data["status"] in _enum_values(ReportStatus)
    assert data["remitted_at"] is None or is_iso8601_timestamp(data["remitted_at"])


def assert_training_class(data: dict):
    assert_common_fields(data)
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert isinstance(data["instructor_user_id"], str)
    assert isinstance(data["instructor_rate_cents_per_hour"], int)
    assert isinstance(data["facility"], str) and data["facility"]
    assert isinstance(data["rti_credit_value"], int) and data["rti_credit_value"] >= 1
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["start_minute"], int) and data["start_minute"] >= 0
    assert isinstance(data["end_minute"], int)
    assert data["end_minute"] > data["start_minute"]
    assert data["status"] in _enum_values(ClassStatus)


def assert_class_enrollment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["class_id"], str)
    assert isinstance(data["apprentice_id"], str)
    assert data["status"] in _enum_values(EnrollmentStatus)


def assert_pay_claim(data: dict):
    assert_common_fields(data)
    assert isinstance(data["class_id"], str)
    assert isinstance(data["instructor_user_id"], str)
    assert data["pay_basis"] in _enum_values(PayBasis)
    assert data["actual_minutes"] is None or isinstance(data["actual_minutes"], int)
    assert isinstance(data["payable_cents"], int)
    assert data["status"] in _enum_values(ClaimStatus)
    assert data["approved_by_user_id"] is None or isinstance(
        data["approved_by_user_id"], str
    )
    assert data["paid_at"] is None or is_iso8601_timestamp(data["paid_at"])


def assert_funding_allocation(data: dict):
    assert_common_fields(data)
    assert data["category"] in ("INSTRUCTION", "EQUIPMENT", "ADMIN")
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["encumbered_cents"], int)
    assert isinstance(data["spent_cents"], int)
    assert isinstance(data["remaining_cents"], int)
    assert isinstance(data["proposed_by_user_id"], str)
    assert data["approved_by_user_id"] is None or isinstance(
        data["approved_by_user_id"], str
    )
    assert data["status"] in _enum_values(AllocationStatus)


def assert_allocation_ledger(data: dict):
    """PRD §2.6: remaining = amount - encumbered - spent."""
    assert_funding_allocation(data)
    expected = (
        data["amount_cents"] - data["encumbered_cents"] - data["spent_cents"]
    )
    assert data["remaining_cents"] == expected, (
        f"remaining_cents {data['remaining_cents']} != amount "
        f"{data['amount_cents']} - encumbered {data['encumbered_cents']} "
        f"- spent {data['spent_cents']}"
    )


def assert_equipment_purchase(data: dict):
    assert_common_fields(data)
    assert isinstance(data["allocation_id"], str)
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["requested_by_user_id"], str)
    assert data["decided_by_user_id"] is None or isinstance(
        data["decided_by_user_id"], str
    )
    assert data["status"] in _enum_values(PurchaseStatus)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp with or without fractional digits."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_instant_equals(actual: str, expected_iso: str):
    """Two ISO 8601 timestamps denote the same instant (PRD §2.5: comparisons
    against instants, such as due dates, resolve to whole seconds)."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )
