"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Every resource carries the common
system-managed fields (id, created_at, updated_at, version) per the PRD
common-resource-properties section.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp for instant comparisons. The PRD
    specifies three fractional digits, but comparisons must be robust to a
    trailing '.000' being present or absent."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}")


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert isinstance(data["insured_name"], str) and data["insured_name"]
    assert data["coverage_line"] in ("WC", "GL")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expiration_date"])
    assert isinstance(data["estimated_annual_premium_cents"], int)
    assert data["estimated_annual_premium_cents"] > 0
    assert isinstance(data["minimum_premium_cents"], int)
    assert 0 < data["minimum_premium_cents"] <= data["estimated_annual_premium_cents"]
    assert isinstance(data["payroll_estimate_dollars"], int)
    assert data["payroll_estimate_dollars"] > 0
    assert isinstance(data["experience_mod_factor"], (int, float))
    assert isinstance(data["class_code_ids"], list)
    assert data["status"] in ("ACTIVE", "AUDIT_PENDING", "AUDIT_FINALIZED",
                              "CANCELLED")


def assert_auditor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["territory_states"], list)
    assert len(data["territory_states"]) > 0
    assert data["level"] in ("STAFF", "SENIOR")


def assert_classification_code(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["description"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["coverage_line"] in ("WC", "GL")
    assert isinstance(data["rate_per_100_cents"], int)
    assert data["rate_per_100_cents"] > 0
    assert isinstance(data["high_hazard"], bool)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])


def assert_selection_run(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data["run_at"])
    for field in ("evaluated_count", "physical_count", "voluntary_count",
                  "exempt_count"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer")


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["policy_id"])
    assert data["audit_type"] in ("PHYSICAL", "VOLUNTARY_REPORT", "REAUDIT")
    assert is_iso8601_timestamp(data["audit_period_start"])
    assert is_iso8601_timestamp(data["audit_period_end"])
    assert data["status"] in (
        "SELECTED", "RECORDS_REQUESTED", "APPOINTMENT_SCHEDULED",
        "FIELD_WORK_DONE", "RESULT_DRAFTED", "BILLED", "DISPUTED",
        "NONCOMPLIANT_PENDING", "ESTIMATED_BILLED", "CLOSED",
        "SUPERSEDED_BY_REAUDIT", "CANCELLED")
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert isinstance(data["total_premium_base_dollars"], int)
    assert data["total_premium_base_dollars"] >= 0


def assert_records_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["audit_work_order_id"])
    assert data["request_type"] in (
        "PAYROLL_SUMMARY", "TAX_FILINGS", "SUBCONTRACTOR_LIST",
        "CERTIFICATES_OF_INSURANCE", "SALES_LEDGER")
    assert data["status"] in ("OPEN", "RECEIVED", "OVERDUE", "WAIVED")
    assert is_iso8601_timestamp(data["requested_at"])
    assert is_iso8601_timestamp(data["due_at"])


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["audit_work_order_id"])
    assert is_valid_uuid(data["auditor_id"])
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["location_type"] in ("INSURED_PREMISES", "VIRTUAL",
                                     "AUDITOR_OFFICE")
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED", "NO_SHOW",
                              "CANCELLED")


def assert_payroll_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["audit_work_order_id"])
    assert is_valid_uuid(data["class_code_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["gross_payroll_dollars"], int)
    assert data["gross_payroll_dollars"] >= 0
    assert isinstance(data["auditable_payroll_dollars"], int)
    assert data["auditable_payroll_dollars"] >= 0
    assert data["status"] in ("DRAFT", "VERIFIED", "REJECTED")


def assert_subcontractor_exposure(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["audit_work_order_id"])
    assert isinstance(data["subcontractor_name"], str)
    assert isinstance(data["payments_dollars"], int)
    assert data["payments_dollars"] >= 0
    assert is_valid_uuid(data["governing_class_code_id"])
    assert isinstance(data["included_dollars"], int)
    assert data["included_dollars"] >= 0
    assert data["status"] in ("EXCLUDED", "INCLUDED", "PARTIAL_INCLUDED")


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["subcontractor_exposure_id"])
    assert isinstance(data["insurer_name"], str)
    assert isinstance(data["wc_coverage_present"], bool)
    assert isinstance(data["gl_coverage_present"], bool)
    assert is_iso8601_timestamp(data["coverage_effective_date"])
    assert is_iso8601_timestamp(data["coverage_expiration_date"])
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED")


def assert_audit_result(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["audit_work_order_id"])
    assert data["variant"] in ("STANDARD", "ESTIMATED_NONCOMPLIANCE")
    assert data["status"] in ("PRELIMINARY", "ISSUED", "DISPUTED", "SUPERSEDED")
    assert isinstance(data["total_payroll_dollars"], int)
    assert isinstance(data["manual_premium_cents"], int)
    assert isinstance(data["mod_factor_applied"], (int, float))
    assert isinstance(data["earned_premium_cents"], int)


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["audit_result_id"])
    assert data["grounds"] in ("CLASSIFICATION_ERROR", "PAYROLL_ERROR",
                               "SUBCONTRACTOR_INCLUSION", "CERT_REVIEW_ERROR",
                               "OTHER")
    assert is_iso8601_timestamp(data["filed_at"])
    assert data["status"] in ("FILED", "UNDER_REVIEW", "UPHELD", "OVERRULED")


def assert_billing_transaction(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["audit_result_id"])
    assert data["type"] in ("ADDITIONAL_PREMIUM_INVOICE", "RETURN_PREMIUM_CREDIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("ISSUED", "PAID", "APPLIED", "PAST_DUE",
                              "CANCELLED")


def assert_mod_revision(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["policy_id"])
    assert is_valid_uuid(data["source_work_order_id"])
    assert isinstance(data["prior_mod_factor"], (int, float))
    assert isinstance(data["payroll_variance_ratio"], (int, float))
    assert isinstance(data["revised_mod_factor"], (int, float))
    assert 0.75 <= data["revised_mod_factor"] <= 1.50
    assert data["status"] in ("DRAFT", "APPLIED")


def assert_billing_signed_sum_invariant(billings: list, expected_adjustment_cents: int):
    """The PRD fiscal invariant: the signed sum of non-CANCELLED billing
    transactions (invoices positive, credits negative) equals the latest
    issued, non-superseded result's adjustment_cents."""
    signed = 0
    for bill in billings:
        if bill["status"] == "CANCELLED":
            continue
        sign = 1 if bill["type"] == "ADDITIONAL_PREMIUM_INVOICE" else -1
        signed += sign * bill["amount_cents"]
    assert signed == expected_adjustment_cents, (
        f"Signed billing sum {signed} != latest result adjustment "
        f"{expected_adjustment_cents}")
