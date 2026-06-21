"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """id + created_at + updated_at + version (entities with the full quartet)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["open_claim_count"], int) and data["open_claim_count"] >= 0
    assert isinstance(data["current_emr"], (int, float))
    assert 0.75 <= float(data["current_emr"]) <= 2.00, "current_emr must be clamped to [0.75, 2.00]"


def assert_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["policy_number"], str)
    assert isinstance(data["manual_premium_cents"], int) and data["manual_premium_cents"] >= 0
    assert isinstance(data["modified_premium_cents"], int) and data["modified_premium_cents"] >= 0


def assert_worker(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["gross_wages_cents"], int) and data["gross_wages_cents"] >= 0
    assert isinstance(data["weeks_worked"], int) and 1 <= data["weeks_worked"] <= 52
    assert isinstance(data["average_weekly_wage_cents"], int) and data["average_weekly_wage_cents"] >= 0


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["policy_id"])
    assert is_valid_uuid(data["worker_id"])
    assert data["status"] in [
        "REPORTED", "MEDICAL_ONLY", "LOST_TIME", "MMI", "CLOSED", "REOPENED", "DENIED",
    ]
    assert data["claim_class"] in ["UNCLASSIFIED", "MEDICAL_ONLY", "LOST_TIME"]
    assert isinstance(data["disability_days"], int) and data["disability_days"] >= 0
    assert is_iso8601_timestamp(data["date_of_injury"])


def assert_injury_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["report_kind"] in ["FROI", "SROI"]
    assert isinstance(data["maintenance_type_code"], str)
    assert data["edi_status"] in ["DRAFT", "TRANSMITTED", "ACKNOWLEDGED", "REJECTED"]


def assert_wage_statement(data: dict):
    """WageStatement is append-only: id + created_at only (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["average_weekly_wage_cents"], int) and data["average_weekly_wage_cents"] >= 0
    assert isinstance(data["ttd_weekly_rate_cents"], int) and data["ttd_weekly_rate_cents"] >= 0


def assert_benefit_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["benefit_type"] in ["TTD", "TPD", "PPD"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ["POSTED", "VOIDED"]


def assert_impairment_rating(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["whole_body_pct"], (int, float)) and 0 <= float(data["whole_body_pct"]) <= 100
    assert data["rater_role"] in ["TREATING", "IME"]
    assert data["status"] in ["PROPOSED", "DISPUTED", "FINALIZED"]


def assert_rtw_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["light_duty_weekly_cents"], int) and data["light_duty_weekly_cents"] >= 0
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "EXPIRED"]


def assert_reserve(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_id"])
    assert data["severity_tier"] in ["MINOR", "MODERATE", "SEVERE"]
    assert isinstance(data["projected_weeks"], int) and data["projected_weeks"] >= 0
    assert isinstance(data["indemnity_reserve_cents"], int) and data["indemnity_reserve_cents"] >= 0
    assert isinstance(data["medical_reserve_cents"], int) and data["medical_reserve_cents"] >= 0
    assert isinstance(data["indemnity_paid_cents"], int) and data["indemnity_paid_cents"] >= 0
    assert isinstance(data["medical_paid_cents"], int) and data["medical_paid_cents"] >= 0
    assert isinstance(data["total_incurred_cents"], int)


def assert_reserve_invariant(data: dict):
    """total_incurred_cents = sum of the four cumulative columns (PRD §2.6)."""
    expected = (
        data["indemnity_reserve_cents"]
        + data["medical_reserve_cents"]
        + data["indemnity_paid_cents"]
        + data["medical_paid_cents"]
    )
    assert data["total_incurred_cents"] == expected, (
        f"total_incurred_cents {data['total_incurred_cents']} != sum of columns {expected}"
    )
    assert data["indemnity_reserve_cents"] >= 0, "outstanding reserve floored at zero"
    assert data["medical_reserve_cents"] >= 0, "outstanding reserve floored at zero"


def assert_ime_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["examiner_name"], str)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED"]


def assert_experience_mod(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["rating_year"], int)
    assert isinstance(data["mod_factor"], (int, float))
    assert 0.75 <= float(data["mod_factor"]) <= 2.00, "mod_factor must be clamped to [0.75, 2.00]"
