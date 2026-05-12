"""Per-entity assertion helpers verifying field types, ranges, and
PRD-pinned invariants (PRD §2.4, §3, §4).

Each assert_<entity>(data) checks the common-fields envelope and entity-specific
field types/enums. Domain invariants (revenue split sum, settlement allocation
sum) are split into separate helpers for tests that only need the invariant.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Common envelope ──────────────────────────────────────────────────────

def _assert_common_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4: id, created_at, updated_at, version on every persisted entity
    other than AuditLogEntry. id is a server-minted UUID with no prefix."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be int >= 1"


def _assert_append_only_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4: AuditLogEntry has only id and created_at, no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"


# ─── Entity assertions ────────────────────────────────────────────────────

def assert_venue(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Venue")
    assert isinstance(data["chain_id"], str) and len(data["chain_id"]) > 0
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["business_hours"], dict)
    assert isinstance(data["deposit_policy_cents"], int) and 0 <= data["deposit_policy_cents"] <= 1_000_000
    for f in ("revenue_share_bps", "author_royalty_bps", "host_commission_bps", "platform_fee_bps"):
        assert isinstance(data[f], int) and 0 <= data[f] <= 10000, f"Venue.{f} out of [0,10000]"
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_venue_revenue_split_sum(data: Dict[str, Any]) -> None:
    """PRD §2.10: the four base bps fields on each venue must sum to exactly 10000."""
    s = data["revenue_share_bps"] + data["author_royalty_bps"] + data["host_commission_bps"] + data["platform_fee_bps"]
    assert s == 10000, f"Venue bps sum must equal 10000, got {s}"


def assert_room(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Room")
    assert isinstance(data["venue_id"], str) and is_valid_uuid(data["venue_id"])
    assert isinstance(data["name"], str)
    assert isinstance(data["capacity_min"], int) and data["capacity_min"] >= 1
    assert isinstance(data["capacity_max"], int) and data["capacity_max"] >= data["capacity_min"] and data["capacity_max"] <= 20
    assert isinstance(data["turnover_minutes"], int) and 0 <= data["turnover_minutes"] <= 240
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_theme(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Theme")
    assert isinstance(data["chain_id"], str)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["genre"] in ("MYSTERY", "HORROR", "EMOTIONAL", "SCIFI", "COMEDY", "PUZZLE")
    assert data["difficulty"] in ("EASY", "MEDIUM", "HARD", "EXPERT")
    assert isinstance(data["duration_minutes"], int) and 30 <= data["duration_minutes"] <= 360
    assert isinstance(data["min_players"], int) and data["min_players"] >= 1
    assert isinstance(data["max_players"], int) and data["max_players"] >= data["min_players"] and data["max_players"] <= 20
    assert isinstance(data["compatible_room_ids"], list)
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["current_version"], int) and data["current_version"] >= 1
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_maintenance_window(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "MaintenanceWindow")
    assert isinstance(data["room_id"], str) and is_valid_uuid(data["room_id"])
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["starts_at"] < data["ends_at"], "MaintenanceWindow ends_at must be > starts_at"
    assert data["status"] in ("SCHEDULED", "ACTIVE", "CLOSED")


def assert_session_slot(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SessionSlot")
    assert isinstance(data["venue_id"], str) and is_valid_uuid(data["venue_id"])
    assert isinstance(data["room_id"], str) and is_valid_uuid(data["room_id"])
    assert isinstance(data["theme_id"], str) and is_valid_uuid(data["theme_id"])
    assert isinstance(data["theme_version_pinned"], int) and data["theme_version_pinned"] >= 1
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["visibility"] in ("PRIVATE_ONLY", "PUBLIC_TEAMUP")
    assert isinstance(data["required_seats_for_launch"], int) and data["required_seats_for_launch"] >= 1
    assert data["schedule_status"] in ("SCHEDULED", "LIVE", "COMPLETED", "CANCELLED")
    assert data["match_status"] in ("OPEN", "MATCHED", "MATCH_FAILED")
    assert isinstance(data["confirmed_seat_count"], int) and data["confirmed_seat_count"] >= 0
    assert is_iso8601_timestamp(data["match_deadline_at"])


def assert_booking(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Booking")
    assert isinstance(data["slot_id"], str) and is_valid_uuid(data["slot_id"])
    assert isinstance(data["lead_player_id"], str)
    assert isinstance(data["team_player_ids"], list) and len(data["team_player_ids"]) >= 1
    assert data["lead_player_id"] in data["team_player_ids"], "lead_player_id must appear in team_player_ids"
    assert isinstance(data["seat_count"], int) and data["seat_count"] == len(data["team_player_ids"])
    assert isinstance(data["paid_amount_cents"], int) and data["paid_amount_cents"] >= 0
    assert isinstance(data["deposit_held_cents"], int) and data["deposit_held_cents"] >= 0
    assert isinstance(data["refund_total_cents"], int) and data["refund_total_cents"] >= 0
    assert data["status"] in ("PENDING_DEPOSIT", "CONFIRMED", "CHECKED_IN", "SETTLED", "CANCELLED", "REFUNDED")
    if data.get("cancellation_initiator") is not None:
        assert data["cancellation_initiator"] in ("PLAYER", "VENUE", "SYSTEM_MATCH_FAIL", "NO_SHOW")


def assert_waitlist_entry(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "WaitlistEntry")
    assert isinstance(data["slot_id"], str) and is_valid_uuid(data["slot_id"])
    assert isinstance(data["lead_player_id"], str)
    assert isinstance(data["requested_seat_count"], int) and data["requested_seat_count"] >= 1
    assert data["priority_class"] in ("VIP", "STANDARD")
    assert is_iso8601_timestamp(data["enqueued_at"])
    assert data["status"] in ("QUEUED", "PROMOTED", "EXPIRED", "CANCELLED")


def assert_player(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Player")
    assert isinstance(data["display_name"], str)
    assert data["gender"] in ("MALE", "FEMALE", "UNDISCLOSED")
    assert isinstance(data["age"], int) and 12 <= data["age"] <= 99
    assert data["experience_level"] in ("NOVICE", "INTERMEDIATE", "VETERAN")
    assert data["tier"] in ("STANDARD", "VIP")
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["status"] in ("ACTIVE", "BANNED")


def assert_staff_member(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "StaffMember")
    assert isinstance(data["chain_id"], str)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["roles_held"], list) and len(data["roles_held"]) >= 1
    for r in data["roles_held"]:
        assert r in ("HOST", "NPC")
    assert isinstance(data["qualifications"], list)
    assert isinstance(data["max_weekly_minutes"], int) and 0 < data["max_weekly_minutes"] <= 10080
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "TERMINATED")


def assert_staff_assignment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "StaffAssignment")
    assert isinstance(data["slot_id"], str) and is_valid_uuid(data["slot_id"])
    assert isinstance(data["staff_member_id"], str) and is_valid_uuid(data["staff_member_id"])
    assert data["role_type"] in ("HOST", "NPC")
    assert isinstance(data["assignment_minutes"], int) and data["assignment_minutes"] >= 0
    assert data["status"] in ("SCHEDULED", "HANDED_OFF", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_review(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Review")
    assert isinstance(data["booking_id"], str) and is_valid_uuid(data["booking_id"])
    assert isinstance(data["author_player_id"], str)
    assert isinstance(data["theme_score"], int) and 1 <= data["theme_score"] <= 5
    if data.get("host_score") is not None:
        assert isinstance(data["host_score"], int) and 1 <= data["host_score"] <= 5
    assert isinstance(data["venue_score"], int) and 1 <= data["venue_score"] <= 5
    assert isinstance(data["comment"], str)
    assert isinstance(data["spam_signal_count"], int) and data["spam_signal_count"] >= 0
    assert isinstance(data["moderation_round"], int) and data["moderation_round"] >= 0
    assert data["status"] in ("PENDING_MODERATION", "PUBLISHED", "REJECTED", "REVISED", "HIDDEN")


def assert_settlement_run(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SettlementRun")
    assert isinstance(data["chain_id"], str)
    assert is_iso8601_timestamp(data["period_starts_at"])
    assert is_iso8601_timestamp(data["period_ends_at"])
    assert data["period_starts_at"] < data["period_ends_at"], "period_ends_at must be > period_starts_at"
    assert isinstance(data["included_session_ids"], list)
    for f in ("gross_total_cents", "venue_payout_cents", "author_payout_cents", "host_payout_cents", "platform_fee_cents"):
        assert isinstance(data[f], int) and data[f] >= 0
    assert data["status"] in ("DRAFT", "FINALIZED", "REVERSED")


def assert_settlement_payout_invariant(run: Dict[str, Any]) -> None:
    """PRD §3.10: gross_total_cents == author + host + venue + platform."""
    s = run["author_payout_cents"] + run["host_payout_cents"] + run["venue_payout_cents"] + run["platform_fee_cents"]
    assert s == run["gross_total_cents"], (
        f"Settlement invariant breached: payouts sum to {s}, gross_total_cents={run['gross_total_cents']}"
    )


def assert_audit_log_entry(entry: Dict[str, Any]) -> None:
    """PRD §2.4 / §2.7: AuditLogEntry is append-only — id + created_at only.
    No updated_at, no version."""
    _assert_append_only_fields(entry, "AuditLogEntry")
    assert "updated_at" not in entry, "AuditLogEntry must not carry updated_at"
    assert "version" not in entry, "AuditLogEntry must not carry version"
    assert isinstance(entry["actor_user_id"], str)
    assert isinstance(entry["actor_role"], str)
    assert entry["subject_entity_type"] in ("Booking", "Review", "SettlementRun")
    assert isinstance(entry["subject_entity_id"], str)
    assert entry["action"] in (
        "BOOKING_CREATED", "BOOKING_CANCELLED", "BOOKING_NO_SHOW_MARKED",
        "BOOKING_REFUNDED", "REVIEW_SUBMITTED", "REVIEW_PUBLISHED",
        "REVIEW_REJECTED", "REVIEW_HIDDEN", "SETTLEMENT_FINALIZED",
        "SETTLEMENT_REVERSED",
    )
    assert isinstance(entry.get("payload_snapshot"), dict)


# ─── Audit-log query helpers ──────────────────────────────────────────────

def find_audit_entries(
    entries: List[Dict[str, Any]],
    *,
    action: Optional[str] = None,
    subject_entity_id: Optional[str] = None,
    subject_entity_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter an audit-log listing by the supplied dimensions."""
    out = entries
    if action is not None:
        out = [e for e in out if e.get("action") == action]
    if subject_entity_id is not None:
        out = [e for e in out if e.get("subject_entity_id") == subject_entity_id]
    if subject_entity_type is not None:
        out = [e for e in out if e.get("subject_entity_type") == subject_entity_type]
    return out


__all__ = [
    "assert_venue",
    "assert_venue_revenue_split_sum",
    "assert_room",
    "assert_theme",
    "assert_maintenance_window",
    "assert_session_slot",
    "assert_booking",
    "assert_waitlist_entry",
    "assert_player",
    "assert_staff_member",
    "assert_staff_assignment",
    "assert_review",
    "assert_settlement_run",
    "assert_settlement_payout_invariant",
    "assert_audit_log_entry",
    "find_audit_entries",
]
