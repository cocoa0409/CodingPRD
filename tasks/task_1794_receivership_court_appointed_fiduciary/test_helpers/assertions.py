"""Entity assertions and domain invariant checkers (PRD §2.8, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import PRIORITY_CLASS_RANK


def assert_common_fields(data: dict):
    """PRD §2.8 system-managed properties carried by every resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_case(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert isinstance(data["court_jurisdiction"], str) and data["court_jurisdiction"]
    assert isinstance(data["debtor_name"], str) and data["debtor_name"]
    assert isinstance(data["appointed_receiver_name"], str)
    assert is_iso8601_timestamp(data["appointment_effective_at"])
    assert isinstance(data["authority_limit_cents"], int)
    assert isinstance(data["business_operation_authorized"], bool)
    assert is_iso8601_timestamp(data["bar_date"])
    assert isinstance(data["reporting_interval_days"], int)
    assert isinstance(data["operating_reserve_cents"], int)
    assert data["status"] in ("ACTIVE", "DISTRIBUTING", "DISCHARGED")
    assert isinstance(data["cash_on_hand_cents"], int)
    assert isinstance(data["marshalled_value_cents"], int)
    assert isinstance(data["allowed_claims_total_cents"], int)
    assert data["posture"] in ("NORMAL", "CASH_CONSTRAINED")
    assert isinstance(data["report_overdue"], bool)


def assert_asset(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["description"], str)
    assert data["asset_class"] in (
        "REAL_PROPERTY", "CASH", "SECURITIES", "RECEIVABLE", "EQUIPMENT", "OTHER",
    )
    assert isinstance(data["estimated_value_cents"], int)
    assert data["status"] in ("IDENTIFIED", "LIQUIDATED", "ABANDONED")


def assert_claim(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["creditor_name"], str)
    assert data["creditor_type"] in (
        "SECURED", "PRIORITY_TAX", "PRIORITY_WAGE", "GENERAL_UNSECURED", "INVESTOR",
    )
    assert isinstance(data["filed_amount_cents"], int)
    assert data["status"] in ("FILED", "ALLOWED", "DISALLOWED")


def assert_engagement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["professional_name"], str)
    assert isinstance(data["firm_name"], str)
    assert data["role_type"] in ("COUNSEL", "ACCOUNTANT", "AUCTIONEER", "BROKER")
    assert data["fee_arrangement"] in ("HOURLY", "CONTINGENT")
    assert isinstance(data["fee_cap_cents"], int)
    assert isinstance(data["total_fees_paid_cents"], int)
    assert data["status"] in ("PROPOSED", "APPROVED", "DENIED", "EXHAUSTED", "CLOSED")


def assert_fee_application(data: dict):
    assert_common_fields(data)
    assert isinstance(data["engagement_id"], str)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["expenses_cents"], int)
    assert isinstance(data["requested_amount_cents"], int)
    assert data["status"] in ("FILED", "APPROVED", "PAID", "DENIED")


def assert_authorization_request(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["request_type"] in (
        "EXPENDITURE", "ASSET_LIQUIDATION", "ASSET_ABANDONMENT", "BUSINESS_DECISION",
    )
    assert isinstance(data["description"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")


def assert_status_report(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["report_type"] in ("PERIODIC", "FINAL")
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["narrative"], str)
    assert data["status"] in ("FILED", "ACCEPTED", "REJECTED")


def assert_distribution_plan(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["reserve_cents"], int)
    assert isinstance(data["pool_snapshot_cents"], int)
    assert data["status"] in ("FILED", "APPROVED", "EXECUTED", "REJECTED", "WITHDRAWN")


def assert_distribution_payment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["claim_id"], str)
    assert data["priority_class"] in tuple(PRIORITY_CLASS_RANK.keys())
    assert isinstance(data["scheduled_amount_cents"], int)
    assert data["status"] in ("SCHEDULED", "PAID", "VOIDED", "CANCELLED")
