"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_patient(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "COLLECTIONS")
    assert isinstance(data["balance_cents"], int)


def assert_coverage(data: dict):
    _common(data)
    assert data["priority"] in ("PRIMARY", "SECONDARY")
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert isinstance(data["benefits_used_cents"], int)
    assert isinstance(data["deductible_met_cents"], int)


def assert_verification(data: dict):
    _common(data)
    assert data["status"] in ("VERIFIED", "EXPIRED")
    assert is_iso8601_timestamp(data.get("verified_at", "")), "verified_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_claim(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ADJUDICATED", "DENIED", "APPEALED", "CLOSED")
    assert isinstance(data["total_billed_cents"], int)
    assert isinstance(data["appeal_count"], int)


def assert_payment(data: dict):
    _common(data)
    assert data["payer_type"] in ("INSURANCE", "PATIENT")
    assert data["status"] in ("POSTED", "REVERSED")
    assert is_iso8601_timestamp(data.get("posted_at", "")), "posted_at must be ISO 8601"


def assert_membership(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "PAST_DUE", "CANCELLED")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["past_due_periods"], int)


def assert_attachment(data: dict):
    """Attachment is immutable: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_immutable_attachment_shape(data: dict):
    """PRD §2.4 / §3.4: Attachment carries no updated_at and no version."""
    assert "version" not in data, "Attachment must not expose a version field"
    assert "updated_at" not in data, "Attachment must not expose an updated_at field"
