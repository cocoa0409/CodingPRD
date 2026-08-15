"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"{entity}.updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def parse_logical_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime for
    instant-level comparison (independent of fractional-digit formatting)."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc)


def assert_timestamp_equals(actual: str, expected_iso: str):
    """Assert two timestamps denote the same instant."""
    assert parse_logical_instant(actual) == parse_logical_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def assert_bid_package(data: dict):
    _assert_common_fields(data, "BidPackage")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["trade_code"], str) and data["trade_code"]
    assert is_iso8601_timestamp(data.get("bid_due_at", "")), \
        "bid_due_at must be ISO 8601"
    assert isinstance(data["bid_bond_required_pct"], (int, float))
    assert data["status"] in [
        "DRAFT", "PUBLISHED", "BIDDING_CLOSED", "TABULATED",
        "RECOMMENDATION_PENDING", "AWARDED",
    ]
    assert isinstance(data["issued_addendum_count"], int)
    assert isinstance(data["submitted_bid_count"], int)


def assert_subcontractor(data: dict):
    _assert_common_fields(data, "Subcontractor")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["current_prequal_status"] in ["NONE", "SUBMITTED", "APPROVED",
                                              "REJECTED"]


def assert_prequal_application(data: dict):
    _assert_common_fields(data, "PrequalApplication")
    assert is_valid_uuid(data.get("subcontractor_id", "")), \
        "subcontractor_id must be a UUID"
    assert isinstance(data["declared_annual_revenue_cents"], int)
    assert isinstance(data["declared_emr"], (int, float))
    assert isinstance(data["declared_bonding_capacity_cents"], int)
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "EXPIRED"]


def assert_invitation(data: dict):
    _assert_common_fields(data, "Invitation")
    assert is_valid_uuid(data.get("bid_package_id", ""))
    assert is_valid_uuid(data.get("subcontractor_id", ""))
    assert data["status"] in ["SENT", "BIDDING", "DECLINED"]
    assert isinstance(data["plan_room_access_count"], int)


def assert_addendum(data: dict):
    _assert_common_fields(data, "Addendum")
    assert is_valid_uuid(data.get("bid_package_id", ""))
    assert isinstance(data["number"], int) and data["number"] >= 1
    assert isinstance(data["summary"], str)
    assert is_iso8601_timestamp(data.get("issued_at", "")), \
        "issued_at must be ISO 8601"


def assert_addendum_acknowledgment(data: dict):
    _assert_common_fields(data, "AddendumAcknowledgment")
    assert is_valid_uuid(data.get("addendum_id", ""))
    assert is_valid_uuid(data.get("subcontractor_id", ""))
    assert data["status"] in ["PENDING", "ACKNOWLEDGED", "WAIVED"]


def assert_bid(data: dict):
    _assert_common_fields(data, "Bid")
    assert is_valid_uuid(data.get("bid_package_id", ""))
    assert is_valid_uuid(data.get("subcontractor_id", ""))
    assert isinstance(data["base_bid_cents"], int)
    assert isinstance(data["bond_amount_cents"], int)
    assert data["status"] in ["SUBMITTED", "AWARDED", "NOT_AWARDED",
                              "DISQUALIFIED", "WITHDRAWN"]
    assert is_iso8601_timestamp(data.get("submitted_at", "")), \
        "submitted_at must be ISO 8601"


def assert_bid_revision(data: dict):
    """Append-only record: id + created_at, and no updated_at/version keys."""
    assert is_valid_uuid(data.get("id", "")), "BidRevision.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "BidRevision.created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["is_last_minute"], bool)
    assert is_iso8601_timestamp(data.get("revised_at", "")), \
        "revised_at must be ISO 8601"


def assert_leveling_adjustment(data: dict):
    _assert_common_fields(data, "LevelingAdjustment")
    assert is_valid_uuid(data.get("bid_id", ""))
    assert isinstance(data["description"], str)
    assert data["treatment"] in ["GC_ALLOWANCE", "SUB_QUOTE", "EXCLUDED_SCOPE"]
    assert isinstance(data["resolved_amount_cents"], int)


def assert_post_bid_interview(data: dict):
    _assert_common_fields(data, "PostBidInterview")
    assert is_valid_uuid(data.get("bid_id", ""))
    assert isinstance(data["interview_room"], str) and data["interview_room"]
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["status"] in ["SCHEDULED", "HELD"]


def assert_award_recommendation(data: dict):
    _assert_common_fields(data, "AwardRecommendation")
    assert is_valid_uuid(data.get("bid_package_id", ""))
    assert is_valid_uuid(data.get("recommended_bid_id", ""))
    assert isinstance(data["rationale"], str)
    assert isinstance(data["created_by_user_id"], str) and \
        data["created_by_user_id"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "RETURNED"]


def assert_bidder_feedback(data: dict):
    _assert_common_fields(data, "BidderFeedback")
    assert is_valid_uuid(data.get("bid_id", ""))
    assert isinstance(data["leveled_rank"], int) and data["leveled_rank"] >= 1
    assert isinstance(data["leveled_amount_cents"], int)
    assert isinstance(data["winning_leveled_amount_cents"], int)
    assert data["status"] in ["DRAFT", "SENT"]
