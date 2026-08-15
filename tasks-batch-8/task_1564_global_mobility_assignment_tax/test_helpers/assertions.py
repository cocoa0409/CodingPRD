"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["home_country_code"], str) and data["home_country_code"]
    assert isinstance(data["functional_currency"], str)
    assert isinstance(data["cost_overrun_threshold_pct"], int)
    assert isinstance(data["max_assignment_duration_days"], int)
    assert isinstance(data["per_diem_annual_day_cap"], int)
    assert data["status"] == "ACTIVE"
    assert isinstance(data["total_posted_chargeback_cents"], int)


def assert_employee(data: dict):
    _assert_common(data)
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_country_code"], str)
    assert isinstance(data["family_size"], int) and data["family_size"] >= 1
    assert isinstance(data["annual_base_salary_cents"], int) and data["annual_base_salary_cents"] >= 0


def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_name"], str)
    assert isinstance(data["host_country_code"], str)
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert isinstance(data["per_diem_daily_cents"], int) and data["per_diem_daily_cents"] >= 0
    assert isinstance(data["housing_monthly_cap_cents"], int) and data["housing_monthly_cap_cents"] >= 0
    assert isinstance(data["cola_pct"], int) and data["cola_pct"] >= 0
    assert data["status"] == "ACTIVE"


def assert_assignment(data: dict):
    _assert_common(data)
    for fk in ("program_id", "employee_id", "policy_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    assert data["assignment_type"] in ("SHORT_TERM", "LONG_TERM")
    assert isinstance(data["totalization_applies"], bool)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["planned_end_date"], str)
    assert data["status"] in (
        "DRAFT", "PENDING_BU_APPROVAL", "PENDING_MOBILITY_APPROVAL", "ACTIVE",
        "REPATRIATION_PENDING", "REPATRIATED", "CLOSED", "CANCELLED",
    )
    assert data["cost_posture"] in ("NORMAL", "OVERRUN")
    for counter in ("ytd_gross_cents", "ytd_hypo_withheld_cents", "ytd_per_diem_days", "ytd_chargeback_cents"):
        assert isinstance(data[counter], int), f"{counter} must be an integer"


def assert_package(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["letter_title"], str)
    assert isinstance(data["home_base_annual_cents"], int) and data["home_base_annual_cents"] >= 0
    assert isinstance(data["goods_services_differential_pct"], int)
    assert isinstance(data["relocation_lump_sum_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED")
    assert isinstance(data["revision_number"], int)


def assert_split(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["home_payroll_pct"], int)
    assert isinstance(data["host_payroll_pct"], int)
    assert isinstance(data["coc_exempt"], bool)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["period_month"], int) and 1 <= data["period_month"] <= 12
    for money in (
        "total_gross_cents", "home_gross_cents", "host_gross_cents", "per_diem_cents",
        "housing_cents", "hypothetical_tax_cents", "employer_host_tax_cents",
        "employer_socsec_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer"
    assert isinstance(data["per_diem_days"], int)
    assert data["status"] in ("DRAFT", "POSTED", "VOIDED")


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["tax_year"], int)
    for money in ("total_hypo_withheld_cents", "final_hypo_tax_cents", "settlement_amount_cents"):
        assert isinstance(data[money], int)
    assert data["direction"] in ("EMPLOYEE_CREDIT", "EMPLOYEE_DEBIT", "ZERO")
    assert data["status"] in ("CALCULATED", "PENDING_REVIEW", "APPROVED", "DISPUTED", "SETTLED")


def assert_engagement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["tax_year"], int)
    assert data["scope"] in ("HOME_ONLY", "HOST_ONLY", "DUAL")
    assert isinstance(data["vendor_name"], str)
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in (
        "ENGAGED", "DATA_SENT", "DRAFT_RETURNED", "UNDER_REVIEW",
        "REVISION_REQUESTED", "ACCEPTED", "FILED", "CLOSED",
    )
    assert isinstance(data["revision_count"], int)


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["application_ref"], str)
    assert data["status"] in ("REQUESTED", "SUBMITTED", "ISSUED", "REJECTED", "EXPIRED")


def assert_projection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert data["variant"] in ("PROVISIONAL", "ACTUALIZED")
    assert isinstance(data["projected_months"], int)
    assert isinstance(data["monthly_cost_cents"], int)
    assert isinstance(data["total_projected_cents"], int)
    assert data["status"] in ("CURRENT", "SUPERSEDED")


def assert_extension(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["requested_new_end_date"], str)
    assert data["status"] in ("PENDING", "APPROVED", "DECLINED", "SUPERSEDED")


def assert_chargeback(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["business_unit"], str)
    assert data["entry_type"] in ("PERIOD_COST", "SETTLEMENT")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ACCRUED", "POSTED", "VOIDED")
