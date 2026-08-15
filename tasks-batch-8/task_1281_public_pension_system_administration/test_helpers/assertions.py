"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """PRD §2.4: every persisted resource carries id, created_at, updated_at,
    and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


def _assert_nullable_int(data: dict, field: str):
    if data.get(field) is not None:
        assert isinstance(data[field], int), \
            f"{field} must be integer cents when present, got {data[field]!r}"


def assert_pension_fund(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_name"], str) and data["fund_name"]
    assert isinstance(data["cola_rate_pct"], (int, float))
    assert isinstance(data["earnings_limit_annual_cents"], int)


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["employer_code"], str) and data["employer_code"]


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["hire_date"], str)
    assert data["status"] in ["ACTIVE", "INACTIVE", "RETIRED", "SUSPENDED_RTW",
                              "DECEASED"]
    assert isinstance(data["total_service_years"], (int, float))
    _assert_nullable_int(data, "current_annual_salary_cents")
    if data.get("deceased_at") is not None:
        assert isinstance(data["deceased_at"], str)


def assert_contribution_report(data: dict):
    _assert_common(data)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["declared_total_cents"], int)
    assert isinstance(data["accepted_total_cents"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "VARIANCE", "RECONCILED"]


def assert_contribution_line(data: dict):
    _assert_common(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["period_salary_cents"], int)
    assert isinstance(data["contribution_amount_cents"], int)
    assert isinstance(data["service_months"], int)
    assert 1 <= data["service_months"] <= 12
    assert data["status"] in ["PENDING", "ACCEPTED", "REJECTED"]


def assert_service_purchase(data: dict):
    _assert_common(data)
    assert data["purchase_type"] in ["MILITARY", "PRIOR_SERVICE"]
    assert isinstance(data["service_period_start"], str)
    assert isinstance(data["service_period_end"], str)
    assert isinstance(data["years_purchased"], (int, float))
    assert data["status"] in ["REQUESTED", "QUOTED", "PLAN_ACTIVE", "COMPLETED",
                              "CANCELLED", "EXPIRED"]
    for field in ("flat_cost_cents", "actuarial_cost_cents", "quoted_cost_cents",
                  "balance_due_cents"):
        _assert_nullable_int(data, field)
    if data.get("cost_variant") is not None:
        assert data["cost_variant"] in ["FLAT", "ACTUARIAL"]
    if data.get("quote_expires_at") is not None:
        assert isinstance(data["quote_expires_at"], str)
    if data.get("installment_count") is not None:
        assert isinstance(data["installment_count"], int)
        assert 1 <= data["installment_count"] <= 60
    assert isinstance(data.get("refunded_total_cents", 0), int)


def assert_purchase_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["due_date"], str)
    assert data["status"] in ["PENDING", "APPLIED", "REFUNDED"]
    if data.get("applied_at") is not None:
        assert isinstance(data["applied_at"], str)


def assert_retirement_application(data: dict):
    _assert_common(data)
    assert data["option_election"] in ["SINGLE_LIFE", "JOINT_50", "JOINT_100"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "UNDER_REVIEW",
                              "RETURNED_FOR_CORRECTION", "APPROVED", "CANCELLED"]
    _assert_nullable_int(data, "provisional_monthly_cents")
    _assert_nullable_int(data, "final_monthly_cents")


def assert_disability_application(data: dict):
    _assert_common(data)
    assert data["disability_type"] in ["DUTY", "NON_DUTY"]
    assert data["status"] in ["UNDER_MEDICAL_REVIEW", "APPROVED", "DENIED"]
    assert isinstance(data.get("appeal_count", 0), int)


def assert_benefit(data: dict):
    _assert_common(data)
    assert data["benefit_kind"] in ["SERVICE", "DISABILITY"]
    assert isinstance(data["monthly_amount_cents"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["effective_date"], str)
    assert isinstance(data.get("cola_applied_count", 0), int)
    assert isinstance(data.get("rtw_ytd_earnings_cents", 0), int)


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["relationship"], str)
    assert isinstance(data["date_of_birth"], str)
    assert data["status"] in ["DESIGNATED", "REVOKED", "CLAIM_FILED", "PAYABLE",
                              "DENIED"]
    _assert_nullable_int(data, "survivor_monthly_cents")
    if data.get("claim_filed_at") is not None:
        assert isinstance(data["claim_filed_at"], str)


def assert_purchase_money_conserved(purchase: dict, payments: list):
    """PRD §3.4 invariant: the quoted cost always equals the outstanding
    balance plus the amounts still held as APPLIED (no money created or
    destroyed)."""
    applied_sum = sum(p["amount_cents"] for p in payments
                      if p.get("status") == "APPLIED")
    if purchase.get("status") == "PLAN_ACTIVE":
        assert purchase["balance_due_cents"] + applied_sum == \
            purchase["quoted_cost_cents"], (
                f"balance {purchase['balance_due_cents']} + applied {applied_sum} "
                f"!= quoted {purchase['quoted_cost_cents']}")
