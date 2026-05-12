"""Payload factories — one per entity, input fields only.

Each factory emits the exact PRD-declared body schema. Optional fields are
included only when caller provides them, so we never accidentally fill in a
default the PRD said is server-side.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid

from .constants import TEST_DEFAULTS


# ─── Helpers ──────────────────────────────────────────────────────────────

def unique_chain_id(prefix: str = "chain") -> str:
    """Generate a unique chain id (free-form string)."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with Z suffix and ms precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def future_iso(hours: float = 24.0, base: Optional[datetime] = None) -> str:
    """Return ISO 8601 UTC `hours` ahead of `base` (or now)."""
    base = base or datetime.now(tz=timezone.utc)
    return iso_z(base + timedelta(hours=hours))


# ─── Venue ────────────────────────────────────────────────────────────────

def create_venue_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 venue body. Bps fields default to a valid 10000 sum:
    revenue_share=4500 + author_royalty=2000 + host_commission=1500 + platform_fee=2000."""
    defaults = {
        "chain_id": overrides.pop("chain_id", None) or unique_chain_id(),
        "name": unique_name("venue"),
        "timezone": TEST_DEFAULTS["timezone"],
        "business_hours": dict(TEST_DEFAULTS["business_hours"]),
        "deposit_policy_cents": TEST_DEFAULTS["deposit_policy_cents"],
        "revenue_share_bps": TEST_DEFAULTS["revenue_share_bps"],
        "author_royalty_bps": TEST_DEFAULTS["author_royalty_bps"],
        "host_commission_bps": TEST_DEFAULTS["host_commission_bps"],
        "platform_fee_bps": TEST_DEFAULTS["platform_fee_bps"],
    }
    defaults.update(overrides)
    return defaults


def update_venue_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 PATCH body — all fields optional."""
    return dict(overrides)


# ─── Room ─────────────────────────────────────────────────────────────────

def create_room_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 room body."""
    defaults = {
        "name": unique_name("room"),
        "capacity_min": TEST_DEFAULTS["room_capacity_min"],
        "capacity_max": TEST_DEFAULTS["room_capacity_max"],
        "turnover_minutes": TEST_DEFAULTS["room_turnover_minutes"],
    }
    defaults.update(overrides)
    return defaults


# ─── MaintenanceWindow ────────────────────────────────────────────────────

def create_maintenance_window_payload(starts_at: str, ends_at: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """PRD §3.1 maintenance-window body."""
    body: Dict[str, Any] = {"starts_at": starts_at, "ends_at": ends_at}
    if reason is not None:
        body["reason"] = reason
    return body


# ─── Theme ────────────────────────────────────────────────────────────────

def create_theme_payload(chain_id: str, compatible_room_ids: List[str], **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 theme body."""
    defaults: Dict[str, Any] = {
        "chain_id": chain_id,
        "title": unique_name("theme"),
        "genre": TEST_DEFAULTS["theme_genre"],
        "difficulty": TEST_DEFAULTS["theme_difficulty"],
        "duration_minutes": TEST_DEFAULTS["theme_duration_minutes"],
        "min_players": TEST_DEFAULTS["theme_min_players"],
        "max_players": TEST_DEFAULTS["theme_max_players"],
        "compatible_room_ids": list(compatible_room_ids),
        "base_price_cents": TEST_DEFAULTS["theme_base_price_cents"],
    }
    defaults.update(overrides)
    return defaults


def publish_theme_revision_payload(bumps_version: bool = True) -> Dict[str, Any]:
    """PRD §3.2: body must explicitly set bumps_version to true."""
    return {"bumps_version": bumps_version}


# ─── SessionSlot ──────────────────────────────────────────────────────────

def create_session_slot_payload(
    theme_id: str,
    starts_at: str,
    visibility: str,
    required_seats_for_launch: int,
    *,
    price_cents: Optional[int] = None,
    match_preferences: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """PRD §3.3 session-slot body."""
    body: Dict[str, Any] = {
        "theme_id": theme_id,
        "starts_at": starts_at,
        "visibility": visibility,
        "required_seats_for_launch": required_seats_for_launch,
    }
    if price_cents is not None:
        body["price_cents"] = price_cents
    if match_preferences is not None:
        body["match_preferences"] = match_preferences
    return body


# ─── Booking ──────────────────────────────────────────────────────────────

def create_booking_payload(team_player_ids: List[str]) -> Dict[str, Any]:
    """PRD §3.5: body carries team_player_ids; the acting Player is the lead.
    Per PRD §3.5 the lead player MUST appear in team_player_ids.
    """
    return {"team_player_ids": list(team_player_ids)}


def confirm_deposit_payload(idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if idempotency_key is not None:
        body["idempotency_key"] = idempotency_key
    return body


def refund_booking_payload(refund_amount_cents: int) -> Dict[str, Any]:
    return {"refund_amount_cents": refund_amount_cents}


# ─── WaitlistEntry ────────────────────────────────────────────────────────

def create_waitlist_entry_payload(requested_seat_count: int) -> Dict[str, Any]:
    return {"requested_seat_count": requested_seat_count}


# ─── Player ───────────────────────────────────────────────────────────────

def create_player_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.5 player body."""
    defaults: Dict[str, Any] = {
        "display_name": unique_name("player"),
        "gender": "UNDISCLOSED",
        "age": TEST_DEFAULTS["player_age"],
        "experience_level": "INTERMEDIATE",
    }
    defaults.update(overrides)
    return defaults


# ─── StaffMember ──────────────────────────────────────────────────────────

def create_staff_member_payload(chain_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8 staff-member body."""
    defaults: Dict[str, Any] = {
        "chain_id": chain_id,
        "display_name": unique_name("staff"),
        "roles_held": ["HOST"],
        "qualifications": [],
        "max_weekly_minutes": TEST_DEFAULTS["staff_max_weekly_minutes"],
    }
    defaults.update(overrides)
    return defaults


# ─── StaffAssignment ──────────────────────────────────────────────────────

def create_staff_assignment_payload(slot_id: str, staff_member_id: str, role_type: str) -> Dict[str, Any]:
    return {
        "slot_id": slot_id,
        "staff_member_id": staff_member_id,
        "role_type": role_type,
    }


def handoff_staff_assignment_payload(substitute_staff_member_id: str) -> Dict[str, Any]:
    return {"substitute_staff_member_id": substitute_staff_member_id}


# ─── Review ───────────────────────────────────────────────────────────────

def create_review_payload(
    *,
    theme_score: int,
    venue_score: int,
    comment: str,
    host_score: Optional[int] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "theme_score": theme_score,
        "venue_score": venue_score,
        "comment": comment,
    }
    if host_score is not None:
        body["host_score"] = host_score
    return body


def patch_review_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.9 PATCH body — all fields optional."""
    return dict(overrides)


def moderate_review_payload(decision: str) -> Dict[str, Any]:
    return {"decision": decision}


# ─── SettlementRun ────────────────────────────────────────────────────────

def create_settlement_run_payload(chain_id: str, period_starts_at: str, period_ends_at: str) -> Dict[str, Any]:
    return {
        "chain_id": chain_id,
        "period_starts_at": period_starts_at,
        "period_ends_at": period_ends_at,
    }


# ─── Inbound events ───────────────────────────────────────────────────────

def payment_confirmed_payload(booking_id: str, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"booking_id": booking_id}
    if idempotency_key is not None:
        body["idempotency_key"] = idempotency_key
    return body


def script_authorization_revoked_payload(theme_id: str, revoked_version: int) -> Dict[str, Any]:
    return {"theme_id": theme_id, "revoked_version": revoked_version}
