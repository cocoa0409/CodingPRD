"""Entity assertions and domain invariant checkers.

Monetary fields are integer cents (PRD §2.5). InsuranceEstimate is immutable and
carries only id + created_at (PRD §2.4) — its assertion omits updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_full(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_drug(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["ndc"], str) and len(data["ndc"]) > 0
    assert isinstance(data["is_controlled"], bool)
    assert isinstance(data["awp_cents"], int) and data["awp_cents"] >= 1
    assert data["form"] in ["TABLET", "CAPSULE", "LIQUID", "INJECTION"]


def assert_pharmacy(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["dispense_fee_cents"], int) and data["dispense_fee_cents"] >= 0
    assert isinstance(data["is_mail_order"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_price_quote(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["cash_price_cents"], int)
    assert isinstance(data["discount_price_cents"], int)
    assert isinstance(data["gold_price_cents"], int)
    assert data["status"] in ["PUBLISHED", "EXPIRED"]


def assert_member(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["has_insurance"], bool)
    assert isinstance(data["lifetime_savings_cents"], int)


def assert_gold_membership(data: dict):
    _assert_audit_full(data)
    assert data["tier"] in ["GOLD_INDIVIDUAL", "GOLD_FAMILY"]
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert data["billing_status"] in ["PENDING_PAYMENT", "PAID", "PAST_DUE"]
    assert data["access_status"] in ["INACTIVE", "ACTIVE", "REVOKED"]


def assert_discount_card(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["bin"], str)
    assert isinstance(data["pcn"], str)
    assert isinstance(data["group_code"], str)
    assert data["pricing_basis"] in ["DISCOUNT", "GOLD"]
    assert data["status"] in ["ISSUED", "REDEEMED", "VOID"]


def assert_price_comparison(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["candidate_count"], int)
    assert data["status"] in ["OPEN", "RESOLVED", "NO_RESULTS", "CONVERTED"]


def assert_claim(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["quantity"], int)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert isinstance(data["savings_cents"], int)
    assert isinstance(data["copay_offset_cents"], int)
    assert data["status"] in ["SUBMITTED", "ADJUDICATED", "REVERSED", "REJECTED"]


def assert_copay_card(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["max_benefit_cents"], int)
    assert isinstance(data["per_fill_cap_cents"], int)
    assert isinstance(data["remaining_benefit_cents"], int)
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "WITHDRAWN"]


def assert_copay_link(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["applied_offset_cents"], int)
    assert data["status"] in ["LINKED", "APPLIED", "RELEASED"]


def assert_mail_order(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["quantity"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ["PLACED", "SHIPPED", "DELIVERED", "CANCELLED"]


def assert_telehealth_referral(data: dict):
    _assert_audit_full(data)
    assert data["reason"] in ["NO_RESULTS", "PRICE_TOO_HIGH", "NEW_PRESCRIPTION"]
    assert data["status"] in ["REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_insurance_estimate(data: dict):
    """Immutable entity: id + created_at only, plus its computed recommendation."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["recommended_path"] in ["DISCOUNT", "INSURANCE", "TIE_DISCOUNT"]
