"""Entity assertions and domain invariant checkers (PRD §2.4, §3.1–§3.7)."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_common_fields(data: dict) -> None:
    """PRD §2.4: every entity carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int>=1, got {data.get('version')!r}"
    )


def assert_employer(data: dict) -> None:
    """PRD §3.1: Employer shape."""
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["state_code"] in {
        "CA",
        "NY",
        "NJ",
        "MA",
        "WA",
        "CT",
        "RI",
        "CO",
        "OR",
        "FED",
    }
    assert data["fmla_method"] in {"ROLLING_BACKWARD", "CALENDAR_YEAR"}
    assert isinstance(data["pfl_enabled"], bool)
    assert 0.0 <= data["employer_premium_share_pct"] <= 1.0
    assert isinstance(data["monthly_premium_total_cents"], int)
    assert data["monthly_premium_total_cents"] >= 0


def assert_employee(data: dict) -> None:
    """PRD §3.3: Employee shape."""
    assert_common_fields(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_iso8601_timestamp(data["hire_date"])
    assert isinstance(data["hours_worked_trailing_12mo"], int)
    assert data["hours_worked_trailing_12mo"] >= 0
    assert isinstance(data["health_plan_enrolled"], bool)
    assert data["employment_status"] in {"ACTIVE", "ON_LEAVE", "TERMINATED"}


def assert_provider(data: dict) -> None:
    """PRD §3.5: HealthcareProvider shape."""
    assert_common_fields(data)
    assert isinstance(data["license_id"], str) and len(data["license_id"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_leave_case(data: dict) -> None:
    """PRD §3.4: LeaveCase shape."""
    assert_common_fields(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["status"] in {
        "SUBMITTED",
        "ELIGIBILITY_PENDING",
        "CERTIFICATION_PENDING",
        "APPROVED",
        "DENIED",
        "ACTIVE",
        "COMPLETED",
        "JOB_RESTORED",
        "JOB_FORFEITED",
    }
    assert data["qualifying_reason"] in {
        "OWN_SERIOUS_HEALTH_CONDITION",
        "FAMILY_SERIOUS_HEALTH_CONDITION",
        "NEW_CHILD_BONDING",
        "MILITARY_CAREGIVER",
        "QUALIFYING_EXIGENCY",
    }
    assert data["leave_type"] in {"CONTINUOUS", "INTERMITTENT", "REDUCED_SCHEDULE"}


def assert_certification_record(data: dict) -> None:
    """PRD §3.5: CertificationRecord shape."""
    assert_common_fields(data)
    assert is_valid_uuid(data["leave_case_id"])
    assert is_valid_uuid(data["provider_id"])
    assert data["certification_status"] in {
        "PENDING",
        "RECEIVED",
        "INSUFFICIENT",
        "COMPLETE",
        "RECERTIFICATION_REQUESTED",
    }


def assert_leave_interval(data: dict) -> None:
    """PRD §3.6: LeaveInterval shape."""
    assert_common_fields(data)
    assert is_valid_uuid(data["leave_case_id"])
    assert is_iso8601_timestamp(data["start_datetime"])
    assert is_iso8601_timestamp(data["end_datetime"])
    assert data["status"] in {"RECORDED", "REVERSED"}


def assert_benefit_ledger(data: dict) -> None:
    """PRD §3.7: BenefitContinuationLedger shape."""
    assert_common_fields(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["leave_case_id"])
    assert data["payment_status"] in {"PENDING", "PARTIAL", "PAID", "DELINQUENT"}


def assert_notice(data: dict) -> None:
    """PRD §2.10: Notice shape."""
    assert_common_fields(data)
    assert is_valid_uuid(data["leave_case_id"])
    assert data["notice_type"] in {
        "ELIGIBILITY_NOTICE",
        "RIGHTS_RESPONSIBILITIES_NOTICE",
        "DESIGNATION_NOTICE",
        "CERTIFICATION_DEMAND",
        "RECERTIFICATION_REQUEST",
    }


def assert_owes_invariant(data: dict) -> None:
    """PRD §3.7: employee_owes_cents == employee_premium_share_cents - payments_received_cents."""
    expected_owes = data["employee_premium_share_cents"] - data["payments_received_cents"]
    assert data["employee_owes_cents"] == expected_owes, (
        f"owes invariant violated: {data['employee_owes_cents']} != "
        f"{data['employee_premium_share_cents']} - {data['payments_received_cents']}"
    )
