"""Entity assertions and domain invariant checkers.

Each assert_<entity>(data) checks the structural contract of the response:
required identifiers, common fields, and status enum membership. Specific
field-value assertions live in the tests themselves.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, has_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if has_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive integer, got {data.get('version')!r}"
        )


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert data["account_status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["lifetime_visits_completed"], int)


def assert_yard(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["address_line1"], str) and data["address_line1"]
    assert isinstance(data["city"], str) and data["city"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["postal_code"], str) and data["postal_code"]
    assert isinstance(data["yard_size_sqft"], int)
    assert isinstance(data["pet_count"], int)
    assert isinstance(data["service_region_code"], str)


def assert_access_profile(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("yard_id", ""))
    assert data["access_status"] in ("VERIFICATION_PENDING", "VERIFIED", "SUSPENDED")
    assert data["pet_aggression_flag"] in ("NONE", "CAUTION", "AGGRESSIVE")


def assert_subscription_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert data["visit_frequency"] in ("WEEKLY", "BIWEEKLY", "TWICE_WEEKLY", "DAILY")
    assert isinstance(data["applies_to_multifamily"], bool)
    assert isinstance(data["base_monthly_fee_cents"], int)
    assert isinstance(data["yard_tier_thresholds"], list)
    assert isinstance(data["yard_tier_surcharges_cents"], list)
    assert isinstance(data["pet_tier_thresholds"], list)
    assert isinstance(data["pet_tier_surcharges_cents"], list)
    assert data["plan_status"] in ("ACTIVE", "RETIRED")


def assert_service_addon(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["addon_code"], str) and data["addon_code"]
    assert isinstance(data["price_cents_per_visit"], int)
    assert data["addon_status"] in ("ACTIVE", "RETIRED")


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("yard_id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "CANCELLED")


def assert_service_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["service_region_code"], str)
    assert isinstance(data["max_visit_capacity"], int) and data["max_visit_capacity"] >= 1
    assert isinstance(data["committed_visit_count"], int) and data["committed_visit_count"] >= 0
    assert isinstance(data["route_load_factor_bp"], int) and data["route_load_factor_bp"] >= 0
    assert data["route_status"] in ("PLANNED", "PUBLISHED", "IN_PROGRESS", "CLOSED")


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert isinstance(data["certified_for_aggressive_pets"], bool)
    assert isinstance(data["active"], bool)


def assert_vacation_window(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert data["skip_reason"] in ("VACATION", "WEATHER_HOLD", "CUSTOMER_REQUEST", "HOA_DIRECTIVE")
    assert data["window_status"] in ("SCHEDULED", "APPLIED", "CANCELLED")


def assert_visit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert data["status"] in (
        "SCHEDULED", "EN_ROUTE", "ON_SITE", "COMPLETED", "SKIPPED", "MISSED", "CANCELLED",
    )


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["invoice_status"] in ("OPEN", "FINALIZED", "PAID", "DISPUTED", "RESOLVED")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["credits_applied_cents"], int)
    assert isinstance(data["total_due_cents"], int)


def assert_invoice_line_item(data: dict):
    """InvoiceLineItem is the one entity WITHOUT updated_at and version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "line item id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    # The immutability contract: no updated_at, no version keys present.
    assert "updated_at" not in data, "InvoiceLineItem must not expose updated_at"
    assert "version" not in data, "InvoiceLineItem must not expose version"
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert data["line_type"] in (
        "SUBSCRIPTION_FEE_PRORATED", "VISIT_CHARGE", "ADDON_CHARGE",
        "VACATION_CREDIT", "SATISFACTION_CREDIT", "ADJUSTMENT",
    )
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_satisfaction_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("visit_id", ""))
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert data["issue_category"] in (
        "MISSED_SPOT", "LATE_ARRIVAL", "GATE_ISSUE", "PET_SAFETY", "BILLING", "OTHER",
    )
    assert data["report_status"] in ("SUBMITTED", "UNDER_REVIEW", "RESOLVED", "ESCALATED")
