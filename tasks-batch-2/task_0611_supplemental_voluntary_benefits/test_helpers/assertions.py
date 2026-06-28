"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names match the PRD verbatim.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"


def _assert_common_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_employer(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["section_125_plan_active"], bool)
    assert data["pay_periods_per_year"] in (52, 26, 24, 12)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_plan_product(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["employer_id"])
    assert data["policy_type"] in (
        "ACCIDENT",
        "CRITICAL_ILLNESS",
        "HOSPITAL_INDEMNITY",
    )
    assert isinstance(data["product_name"], str)
    assert data["weekly_premium_cents"] >= 0
    assert data["eoi_surcharge_bps"] >= 0
    assert data["annual_benefit_cap_cents"] >= 0
    assert data["portability_loadup_bps"] >= 0
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")


def assert_schedule_item(data: dict):
    # common_fields: false — must NOT carry version/updated_at
    _assert_common(data)
    assert "version" not in data, "BenefitScheduleItem must have no version field"
    assert (
        "updated_at" not in data
    ), "BenefitScheduleItem must have no updated_at field"
    assert is_valid_uuid(data["plan_product_id"])
    assert isinstance(data["event_code"], str)
    assert data["flat_benefit_cents"] >= 0
    assert data["lifetime_max_occurrences"] >= 0
    assert isinstance(data["is_wellness"], bool)


def assert_enrollment_period(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["label"], str)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED")


def assert_employee(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["employer_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["employment_status"] in ("EMPLOYED", "TERMINATED")
    assert data["total_weekly_deduction_cents"] >= 0


def assert_disbursement_account(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["routing_number"], str)
    assert isinstance(data["account_last4"], str)
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED")
    assert isinstance(data["is_default"], bool)


def assert_enrollment(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["plan_product_id"])
    assert is_valid_uuid(data["enrollment_period_id"])
    assert data["gi_status"] in ("GUARANTEED_ISSUE", "EVIDENCE_REQUIRED")
    assert data["weekly_premium_cents"] >= 0
    assert data["weekly_deduction_cents"] >= 0
    assert data["benefit_paid_cents"] >= 0
    assert data["benefit_remaining_cents"] >= 0
    assert data["lifecycle_status"] in (
        "PENDING",
        "ACTIVE",
        "TERMINATED",
        "PORTED",
        "DECLINED",
    )
    assert data["funding_status"] in ("UNFUNDED", "CURRENT", "LAPSED")


def assert_enrollment_ledger_invariants(data: dict, cap_cents: int):
    """The benefit ledger must always reconcile: remaining = max(0, cap - paid)."""
    assert data["benefit_paid_cents"] >= 0
    expected_remaining = max(0, cap_cents - data["benefit_paid_cents"])
    assert data["benefit_remaining_cents"] == expected_remaining, (
        f"benefit_remaining_cents {data['benefit_remaining_cents']} != "
        f"max(0, {cap_cents} - {data['benefit_paid_cents']}) = {expected_remaining}"
    )


def assert_payroll_deduction(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["pay_period_index"] >= 0
    assert data["amount_cents"] >= 0
    assert data["outcome"] in ("POSTED", "FAILED")


def assert_claim(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["disbursement_account_id"])
    assert isinstance(data["event_code"], str)
    assert data["claimed_cents"] >= 0
    assert data["approved_cents"] >= 0
    assert data["paid_cents"] >= 0
    assert data["status"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "APPROVED",
        "DENIED",
        "PAID",
        "VOIDED",
    )


def assert_disbursement(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["disbursement_account_id"])
    assert data["amount_cents"] >= 0
    assert data["status"] in ("INITIATED", "SETTLED", "RETURNED")


def assert_portability_conversion(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["direct_bill_weekly_cents"] >= 0
    assert data["status"] in ("CONVERTED", "CANCELLED")


def assert_section125_election(data: dict):
    _assert_common_versioned(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["plan_year_label"], str)
    assert data["annual_pretax_amount_cents"] >= 0
    assert data["status"] in ("LOCKED", "REVOKED")
