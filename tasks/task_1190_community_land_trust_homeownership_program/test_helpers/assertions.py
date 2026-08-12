"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_common_fields(data: dict, *, has_updated_and_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if has_updated_and_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be an int >= 1, got {data.get('version')!r}"
        )


def assert_clt_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("area_median_income_cents"), int)
    assert isinstance(data.get("max_eligibility_ami_pct"), (int, float))
    assert isinstance(data.get("ground_lease_base_fee_cents"), int)
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert data.get("resale_formula_kind") in ("APPRAISAL_BASED", "INDEXED")


def assert_household(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("legal_name"), str)
    assert isinstance(data.get("household_size"), int) and data["household_size"] >= 1
    assert isinstance(data.get("annual_gross_income_cents"), int)
    assert data.get("eligibility_status") in (
        "PENDING", "ELIGIBLE", "INELIGIBLE", "SUSPENDED", "EXPIRED",
    )


def assert_income_certification(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("tax_year"), int)
    assert isinstance(data.get("reported_annual_income_cents"), int)
    assert isinstance(data.get("verified_annual_income_cents"), int)
    assert isinstance(data.get("household_size_at_cert"), int)
    assert data.get("status") in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "EXPIRED",
    )


def assert_education_course(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("code"), str)
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("credit_hours"), int)
    assert data.get("status") in ("OFFERED", "RETIRED")


def assert_education_completion(data: dict):
    """Append-only entity: carries ONLY id + created_at, NOT updated_at / version."""
    assert_common_fields(data, has_updated_and_version=False)
    assert "updated_at" not in data, "EducationCompletion must not expose updated_at"
    assert "version" not in data, "EducationCompletion must not expose version"
    assert isinstance(data.get("course_id"), str)
    assert isinstance(data.get("completed_at"), str)
    assert isinstance(data.get("expires_at"), str)
    assert isinstance(data.get("score_pct"), (int, float))


def assert_unit(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("address"), str)
    assert isinstance(data.get("bedrooms"), int)
    assert isinstance(data.get("original_subsidy_cents"), int)
    assert isinstance(data.get("original_sale_price_cents"), int)
    assert data.get("occupancy_status") in (
        "VACANT", "OCCUPIED", "LISTED_FOR_RESALE", "UNDER_CONTRACT",
        "IN_DEFAULT", "FORECLOSED",
    )
    assert data.get("maintenance_flag") in ("OK", "NEEDS_REPAIR", "UNSAFE")


def assert_ground_lease(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("household_id"), str)
    assert isinstance(data.get("start_date"), str)
    assert isinstance(data.get("purchase_price_cents"), int)
    assert data.get("status") in (
        "DRAFT", "ACTIVE", "IN_DEFAULT", "CURE_PERIOD",
        "FORECLOSED", "TERMINATED", "EXPIRED",
    )


def assert_lease_fee(data: dict):
    """Append-only entity: carries ONLY id + created_at, NOT updated_at / version."""
    assert_common_fields(data, has_updated_and_version=False)
    assert "updated_at" not in data, "LeaseFee must not expose updated_at"
    assert "version" not in data, "LeaseFee must not expose version"
    assert isinstance(data.get("period_year"), int)
    assert isinstance(data.get("period_month"), int)
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("paid_amount_cents"), int)
    assert data.get("status") in ("PENDING", "PAID", "LATE", "WAIVED", "DEFAULTED")


def assert_default_notice(data: dict):
    assert_common_fields(data)
    assert data.get("notice_kind") in (
        "FEE_ARREARS", "MAINTENANCE", "UNAUTHORIZED_REFINANCE", "OCCUPANCY_VIOLATION",
    )
    assert isinstance(data.get("amount_due_cents"), int)
    assert data.get("status") in ("OPEN", "CURED", "ESCALATED", "DISMISSED")


def assert_inspection_record(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("scheduled_for"), str)
    assert data.get("result") in ("PENDING", "PASSED", "FAILED", "NEEDS_REPAIR")


def assert_waitlist_entry(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("desired_bedrooms"), int)
    assert isinstance(data.get("max_price_cents"), int)
    assert isinstance(data.get("priority_score"), int)
    assert data.get("status") in (
        "ACTIVE", "MATCHED", "WITHDRAWN", "EXPIRED", "FULFILLED",
    )


def assert_resale_listing(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("asking_price_cents"), int)
    assert isinstance(data.get("seller_proceeds_cents"), int)
    assert isinstance(data.get("subsidy_retained_cents"), int)
    assert data.get("status") in (
        "OPEN", "MATCHED", "UNDER_CONTRACT", "CLOSED", "CANCELLED",
    )


def assert_refinance_request(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("lender_name"), str)
    assert isinstance(data.get("requested_loan_cents"), int)
    assert isinstance(data.get("requested_cash_out_cents"), int)
    assert isinstance(data.get("appraised_value_cents"), int)
    assert data.get("status") in (
        "SUBMITTED", "LENDER_REVIEW", "APPROVED", "REJECTED", "WITHDRAWN", "RECORDED",
    )
