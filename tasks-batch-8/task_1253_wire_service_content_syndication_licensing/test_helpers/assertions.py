"""Entity assertions and domain invariant checkers (wire service PRD)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits) to datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_common_fields(data: dict):
    """Every persisted resource carries id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"version must be int, got {data.get('version')!r}"


def assert_content_package(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["display_name"], str)
    assert data["media_rights"] in ("TEXT_ONLY", "TEXT_AND_PHOTO", "TEXT_PHOTO_VIDEO")
    assert isinstance(data["base_monthly_fee_cents"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_subscriber_tier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["min_audience"], int)
    assert data["max_audience"] is None or isinstance(data["max_audience"], int)
    assert isinstance(data["circulation_multiplier_basis_points"], int)
    assert isinstance(data["monthly_republish_quota"], int)
    assert isinstance(data["overage_per_article_cents"], int)
    assert isinstance(data["member_discount_pct"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_feed(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["topic"] in ("NATIONAL", "WORLD", "BUSINESS", "SPORTS", "FEATURES")
    assert isinstance(data["embargo_window_minutes"], int)
    assert data["status"] in ("LIVE", "SUSPENDED")


def assert_subscriber(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["billing_email"], str)
    assert isinstance(data["declared_audience"], int)
    assert isinstance(data["is_member"], bool)
    assert isinstance(data["member_credit_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert is_valid_uuid(data.get("package_id", ""))
    assert isinstance(data["months_used_current_period"], int)
    assert isinstance(data["republish_count_current_month"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "CANCELLED")


def assert_entitlement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("feed_id", ""))
    assert data["status"] in ("LIVE", "REVOKED")


def assert_article(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("feed_id", ""))
    assert isinstance(data["headline"], str)
    assert isinstance(data["body_word_count"], int)
    assert isinstance(data["slug"], str) and len(data["slug"]) > 0
    assert data["embargo_status"] in ("CLEAR", "EMBARGOED", "EMBARGO_LIFTED")
    assert data["status"] in ("DRAFT", "PUBLISHED", "WITHDRAWN", "TAKEN_DOWN")


def assert_asset(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("article_id", ""))
    assert data["kind"] in ("PHOTO", "VIDEO")
    assert data["rights_scope"] in ("WIRE", "EDITORIAL_ONLY", "MEMBER_ONLY")
    assert isinstance(data["file_ref"], str)
    assert data["status"] in ("ACTIVE", "TAKEN_DOWN")


def assert_publication(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("article_id", ""))
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["within_quota"], bool)
    assert data["status"] in ("RECORDED", "AUDIT_FLAGGED", "DISMISSED")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert isinstance(data["billing_month"], str)
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["overage_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOIDED")


def assert_clock_checkpoint(data: dict):
    """ClockCheckpoint carries only id and created_at; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("current_utc", "")), (
        f"current_utc must be ISO 8601, got {data.get('current_utc')!r}"
    )
    assert "updated_at" not in data, "ClockCheckpoint must not carry updated_at"
    assert "version" not in data, "ClockCheckpoint must not carry version"


def assert_invoice_fiscal_invariants(data: dict):
    """Invoice arithmetic invariants that must hold after generation and issuance."""
    assert data["total_due_cents"] >= 0, "total_due_cents can never fall below zero"
    assert data["member_credit_applied_cents"] >= 0
