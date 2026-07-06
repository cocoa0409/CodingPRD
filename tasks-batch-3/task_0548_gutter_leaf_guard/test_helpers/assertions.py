"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the shape and system-managed fields the PRD
guarantees on that resource. Value-level business assertions (exact totals,
statuses) live in the test files themselves.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AppointmentStatus,
    FinancingPlanStatus,
    JobStatus,
    LeadStatus,
    ProductCategory,
    QuoteStatus,
    ReferralStatus,
    WarrantyClaimStatus,
)


def _assert_common_system_fields(data: dict):
    """The four common fields every resource carries (PRD Section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_product(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in [c.value for c in ProductCategory]
    assert isinstance(data["base_rate_cents_per_foot"], int)
    assert isinstance(data["available_colors"], list)
    assert isinstance(data["premium_colors"], list)
    assert isinstance(data["is_active"], bool)


def assert_sales_rep(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["region"], str)
    assert isinstance(data["is_active"], bool)


def assert_crew(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region"], str)
    assert isinstance(data["is_certified_leaf_guard"], bool)
    assert isinstance(data["booked_days"], int) and data["booked_days"] >= 0


def assert_lead(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["sales_rep_id"], str)
    assert data["status"] in [s.value for s in LeadStatus]
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert isinstance(data["credit_balance_cents"], int)


def assert_appointment(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["lead_id"], str)
    assert isinstance(data["sales_rep_id"], str)
    assert data["status"] in [s.value for s in AppointmentStatus]


def assert_quote(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["lead_id"], str)
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["product_id"], str)
    assert data["status"] in [s.value for s in QuoteStatus]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] - data["discount_cents"], \
        "total_cents must equal subtotal_cents - discount_cents"


def assert_financing_plan(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["quote_id"], str)
    assert data["status"] in [s.value for s in FinancingPlanStatus]
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["monthly_payment_cents"], int)
    assert isinstance(data["total_cost_cents"], int)


def assert_job(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["quote_id"], str)
    assert isinstance(data["lead_id"], str)
    assert data["status"] in [s.value for s in JobStatus]
    assert isinstance(data["install_days"], int)
    assert isinstance(data["deposit_cents"], int)


def assert_warranty_claim(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["job_id"], str)
    assert data["status"] in [s.value for s in WarrantyClaimStatus]


def assert_referral(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["referrer_lead_id"], str)
    assert isinstance(data["referee_lead_id"], str)
    assert data["status"] in [s.value for s in ReferralStatus]
    assert isinstance(data["payout_cents"], int)
