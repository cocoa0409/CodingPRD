"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ClaimMode,
    ClaimStatus,
    CurbAlertStatus,
    GiftCategory,
    GiftPostStatus,
    HealthTier,
    JoinPolicy,
    MembershipStatus,
    MemberStatus,
    ModerationActionStatus,
    ModerationActionType,
    PickupPlanStatus,
    ReportStatus,
    ReputationEventStatus,
    RosterStatus,
    WishlistStatus,
)


def _assert_common_fields(data: dict):
    """Standard system-managed fields on primary resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("display_name"), str) and len(data["display_name"]) > 0
    assert data.get("status") in [s.value for s in MemberStatus]
    assert isinstance(data.get("reputation_score"), (int, float))
    assert isinstance(data.get("pending_reputation_score"), (int, float))
    assert isinstance(data.get("fairness_score"), int)
    assert 0 <= data["fairness_score"] <= 100
    assert isinstance(data.get("active_strike_points"), int) and data["active_strike_points"] >= 0
    assert isinstance(data.get("given_count_90d"), int) and data["given_count_90d"] >= 0
    assert isinstance(data.get("received_count_90d"), int) and data["received_count_90d"] >= 0
    assert "suspension_ends_at" in data


def assert_group(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("zip_code"), str) and len(data["zip_code"]) == 5
    assert data.get("join_policy") in [p.value for p in JoinPolicy]
    assert isinstance(data.get("capacity"), int)
    assert isinstance(data.get("member_count"), int) and data["member_count"] >= 0
    assert data.get("roster_status") in [s.value for s in RosterStatus]
    assert isinstance(data.get("health_score"), int)
    assert data.get("health_tier") in [t.value for t in HealthTier]


def assert_membership(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("group_id", ""))
    assert data.get("role") in ["MEMBER", "MODERATOR"]
    assert data.get("status") in [s.value for s in MembershipStatus]


def assert_gift_post(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("group_id", ""))
    assert is_valid_uuid(data.get("giver_id", ""))
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert data.get("category") in [c.value for c in GiftCategory]
    assert data.get("claim_mode") in [m.value for m in ClaimMode]
    assert data.get("status") in [s.value for s in GiftPostStatus]
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert "current_claim_id" in data
    assert "current_offer_expires_at" in data


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("post_id", ""))
    assert is_valid_uuid(data.get("claimer_id", ""))
    assert data.get("status") in [s.value for s in ClaimStatus]
    assert isinstance(data.get("claim_seq"), int) and data["claim_seq"] >= 1
    assert "offered_at" in data
    assert "offer_expires_at" in data


def assert_pickup_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert is_valid_uuid(data.get("proposer_id", ""))
    assert is_valid_uuid(data.get("last_proposer_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 1
    assert data.get("status") in [s.value for s in PickupPlanStatus]


def assert_wishlist(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("group_id", ""))
    assert isinstance(data.get("keyword"), str) and len(data["keyword"]) > 0
    assert data.get("status") in [s.value for s in WishlistStatus]
    assert "matched_post_id" in data
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_curb_alert(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("group_id", ""))
    assert is_valid_uuid(data.get("creator_id", ""))
    assert isinstance(data.get("zone"), str) and len(data["zone"]) > 0
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data.get("status") in [s.value for s in CurbAlertStatus]


def assert_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("group_id", ""))
    assert is_valid_uuid(data.get("reporter_id", ""))
    assert data.get("target_type") in ["MEMBER", "GIFT_POST", "CLAIM", "CURB_ALERT"]
    assert isinstance(data.get("target_id"), str)
    assert data.get("category") in [
        "NO_SHOW", "SAFETY", "SPAM", "PROHIBITED_ITEM", "HARASSMENT", "OTHER"
    ]
    assert data.get("status") in [s.value for s in ReportStatus]
    assert "reviewed_by" in data
    assert is_iso8601_timestamp(data.get("sla_due_at", ""))
    assert "resolved_at" in data


def assert_moderation_action(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("report_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data.get("action_type") in [t.value for t in ModerationActionType]
    assert data.get("status") in [s.value for s in ModerationActionStatus]
    assert is_iso8601_timestamp(data.get("active_until", ""))


def assert_reputation_event(data: dict):
    """Append-only ledger entry: carries id + created_at; NO updated_at, NO version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ReputationEvent must not carry updated_at"
    assert "version" not in data, "ReputationEvent must not carry version"
    assert is_valid_uuid(data.get("member_id", ""))
    assert data.get("event_type") in [
        "WELCOME_BONUS", "GIFT_COMPLETED", "RECEIVE_COMPLETED", "NO_SHOW_PENALTY", "STRIKE_APPLIED"
    ]
    assert isinstance(data.get("base_points"), (int, float))
    assert data.get("status") in [s.value for s in ReputationEventStatus]


def assert_group_invariants(data: dict):
    """Group invariants that must hold after any operation (PRD §3.1, §2.9)."""
    assert data["member_count"] >= 0
    assert data["member_count"] <= data["capacity"]
    if data["member_count"] >= data["capacity"]:
        assert data["roster_status"] == "FULL", "roster_status must be FULL at capacity"
    else:
        assert data["roster_status"] == "ACCEPTING"
    expected_tier = (
        "GREEN" if data["health_score"] >= 20 else "YELLOW" if data["health_score"] >= 0 else "RED"
    )
    assert data["health_tier"] == expected_tier, (
        f"health_tier {data['health_tier']} inconsistent with health_score {data['health_score']}"
    )


def assert_member_invariants(data: dict):
    """Member invariants (PRD §2.8, §2.10)."""
    assert 0 <= data["fairness_score"] <= 100
    assert data["active_strike_points"] >= 0
    if data["status"] == "SUSPENDED":
        assert data.get("suspension_ends_at") is not None, (
            "a SUSPENDED member must carry suspension_ends_at"
        )
    else:
        assert data.get("suspension_ends_at") is None, (
            "suspension_ends_at must be null outside SUSPENDED"
        )


def assert_iso_instant(actual: str, expected: str, msg: str = ""):
    """Instant equality for ISO 8601 timestamps.

    PRD pins the *value* of computed timestamps (e.g. offer_expires_at =
    offered_at + 24h) and mandates three fractional digits only for
    `created_at` and `api_request_timestamp`; the string format of all other
    timestamp fields is left to the implementation, so comparisons must be by
    parsed instant, not by string equality.
    """
    from datetime import datetime

    def _parse(v):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))

    assert _parse(actual) == _parse(expected), (
        msg or f"{actual!r} != {expected!r} (compared as instants)"
    )
