"""Entity assertions and domain invariant checkers (PRD contract)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version must be >= 1"


def assert_user(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["jurisdiction"], str)


def assert_petition(data: dict):
    _assert_common(data)
    assert isinstance(data["author_user_id"], str) and len(data["author_user_id"]) > 0
    assert data["status"] in [s for s in (
        "DRAFT", "UNDER_REVIEW", "CHANGES_REQUESTED", "PUBLISHED",
        "CLOSED_VICTORY", "CLOSED_WITHDRAWN", "REMOVED")]
    assert data["moderation_status"] in ("PENDING", "APPROVED", "BLOCKED")
    assert data["category"] in ("ENVIRONMENT", "POLITICS", "HEALTH", "EDUCATION", "OTHER")
    assert isinstance(data["goal"], int)
    assert isinstance(data["verified_signature_count"], int)
    assert isinstance(data["pending_signature_count"], int)
    assert isinstance(data["goal_reached"], bool)
    assert isinstance(data["milestone_thresholds"], list)
    assert isinstance(data["milestones_reached"], list)


def assert_target(data: dict):
    _assert_common(data)
    assert isinstance(data["petition_id"], str)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "UNREACHABLE")


def assert_representative(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["jurisdiction"], str)


def assert_signature(data: dict):
    _assert_common(data)
    assert isinstance(data["petition_id"], str)
    assert isinstance(data["signer_user_id"], str)
    assert data["status"] in ("PENDING_VERIFICATION", "VERIFIED", "REJECTED", "REVOKED")


def assert_comment(data: dict):
    _assert_common(data)
    assert isinstance(data["petition_id"], str)
    assert data["comment_type"] in ("COMMENT", "UPDATE")
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "FLAGGED", "REMOVED")
    assert isinstance(data["delivered"], bool)


def assert_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["petition_id"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["gross_pledged_cents"], int)
    assert isinstance(data["funds_raised_cents"], int)


def assert_donation(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["donor_user_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "SETTLED", "REFUNDED", "FAILED")


def assert_promotion(data: dict):
    _assert_common(data)
    assert isinstance(data["petition_id"], str)
    assert data["placement_tier"] in ("STANDARD", "PREMIUM", "SPOTLIGHT")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "CANCELLED", "COMPLETED")
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["duration_days"], int)


def assert_delivery_meeting(data: dict):
    _assert_common(data)
    assert isinstance(data["petition_id"], str)
    assert isinstance(data["target_id"], str)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "DELIVERED", "CANCELLED")
