"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the common fields (id UUID, ISO 8601 timestamps, integer
version) and the entity-specific fields against the PRD contract. Monetary fields are integer
cents (PRD 2.5).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["tax_year"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "CLOSED"]
    assert isinstance(data["annual_match_cap_cents"], int)


def assert_employee(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["annual_salary_cents"], int)
    assert isinstance(data["match_consumed_ytd_cents"], int)
    assert isinstance(data["dfd_consumed_ytd_cents"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_charity(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["ein"], str)
    assert isinstance(data["review_rounds"], int)
    assert isinstance(data["total_received_cents"], int)
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "REJECTED", "SUSPENDED",
    ]


def assert_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["charity_id"], str)
    assert isinstance(data["goal_cents"], int)
    assert isinstance(data["raised_cents"], int)
    assert data["status"] in ["DRAFT", "LIVE", "PAUSED", "ENDED"]


def assert_donation(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["campaign_id"], str)
    assert data["donation_type"] in ["ONE_TIME", "RECURRING"]
    assert data["funding_method"] in ["PAYROLL_DEDUCTION", "CREDIT"]
    assert isinstance(data["base_amount_cents"], int)
    assert data["status"] in ["PLEDGED", "AUTHORIZED", "SETTLED", "REFUNDED", "CANCELLED"]


def assert_payroll_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["per_period_amount_cents"], int)
    assert isinstance(data["occurrences_generated"], int)
    assert data["status"] in ["ACTIVE", "PAUSED", "CANCELLED"]


def assert_matching_gift(data: dict):
    _assert_common(data)
    assert isinstance(data["donation_id"], str)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["estimated_match_cents"], int)
    assert isinstance(data["matched_amount_cents"], int)
    assert data["status"] in ["REQUESTED", "FINALIZED", "CAPPED", "SETTLED", "REVERSED"]


def assert_volunteer_log(data: dict):
    _assert_common(data)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["charity_id"], str)
    assert isinstance(data["minutes"], int)
    assert isinstance(data["grant_amount_cents"], int)
    assert data["status"] in ["LOGGED", "APPROVED", "REJECTED", "SETTLED", "REVERSED"]


def assert_disbursement_batch(data: dict):
    _assert_common(data)
    assert isinstance(data["charity_id"], str)
    assert isinstance(data["gross_total_cents"], int)
    assert isinstance(data["admin_fee_cents"], int)
    assert isinstance(data["net_total_cents"], int)
    assert data["status"] in ["OPEN", "LOCKED", "SETTLED", "VOIDED"]


def assert_grant(data: dict):
    _assert_common(data)
    assert isinstance(data["batch_id"], str)
    assert isinstance(data["charity_id"], str)
    assert data["source_type"] in ["DONATION", "MATCH", "DFD"]
    assert isinstance(data["source_id"], str)
    assert isinstance(data["gross_amount_cents"], int)
    assert data["status"] in ["STAGED", "SETTLED", "VOIDED"]


def assert_tax_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["deductible_donations_cents"], int)
    assert isinstance(data["matched_total_cents"], int)
    assert isinstance(data["line_count"], int)
    assert data["status"] in ["GENERATED", "FINAL"]
