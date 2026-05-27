"""Entity assertions and domain invariant checkers.

Per PRD §2.4: Member, Property, Host, GamingSession, CompRoomBooking,
HostAssignment, and AnnualResetRun carry the full common-resource property
set (id, created_at, updated_at, version). SelfExclusion and VelocityAlert
are append-only audit rows: they carry only id + created_at.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


# ─── Common-field helpers ─────────────────────────────────────────────────

def _assert_common_full(data: dict, label: str) -> None:
    """Common-resource-property checks for entities with full common fields
    (id + created_at + updated_at + version), per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be int >= 1, got {data.get('version')!r}"
    )


def _assert_common_append_only(data: dict, label: str) -> None:
    """Common-resource-property checks for append-only audit rows
    (id + created_at only), per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_member(data: dict) -> None:
    _assert_common_full(data, "Member")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert is_valid_uuid(data["home_property_id"])
    assert data["tier_status"] in {"GOLD", "PLATINUM", "DIAMOND", "SEVEN_STARS"}
    assert isinstance(data["tier_credits_ytd"], (int, float))
    assert data["tier_credits_ytd"] >= 0
    assert isinstance(data["tier_credits_lifetime"], (int, float))
    assert data["tier_credits_lifetime"] >= 0
    assert data["exclusion_status"] in {"NOT_EXCLUDED", "EXCLUDED", "REINSTATED"}
    assert data["velocity_status"] in {"NORMAL", "FLAGGED", "SUSPENDED"}
    # assigned_host_id is nullable
    if data.get("assigned_host_id") is not None:
        assert is_valid_uuid(data["assigned_host_id"])


def assert_property(data: dict) -> None:
    _assert_common_full(data, "Property")
    assert isinstance(data["name"], str) and data["name"]
    assert data["market_segment"] in {"VEGAS_STRIP", "REGIONAL", "INTERNATIONAL"}
    assert isinstance(data["base_room_rate_cents"], int)
    assert data["base_room_rate_cents"] >= 0
    assert data["status"] in {"OPEN", "CLOSED"}


def assert_host(data: dict) -> None:
    _assert_common_full(data, "Host")
    assert isinstance(data["employee_email"], str) and "@" in data["employee_email"]
    assert is_valid_uuid(data["home_property_id"])
    assert data["status"] in {"ACTIVE", "INACTIVE"}


def assert_gaming_session(data: dict) -> None:
    _assert_common_full(data, "GamingSession")
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["property_id"])
    assert is_iso8601_timestamp(data["started_at"])
    assert is_iso8601_timestamp(data["ended_at"])
    assert data["game_type"] in {"SLOTS", "TABLE_GAMES", "POKER"}
    assert isinstance(data["theoretical_loss_cents"], int)
    assert data["theoretical_loss_cents"] >= 0
    assert isinstance(data["tier_credits_earned"], (int, float))
    assert data["tier_credits_earned"] >= 0
    assert data["status"] in {"RECORDED", "VOIDED"}


def assert_comp_room_booking(data: dict) -> None:
    _assert_common_full(data, "CompRoomBooking")
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["property_id"])
    assert is_iso8601_timestamp(data["check_in"])
    assert is_iso8601_timestamp(data["check_out"])
    assert isinstance(data["nights"], int) and data["nights"] >= 0
    assert isinstance(data["provisional_rate_cents"], int)
    assert data["provisional_rate_cents"] >= 0
    # final_rate_cents is nullable until check-in
    if data.get("final_rate_cents") is not None:
        assert isinstance(data["final_rate_cents"], int)
        assert data["final_rate_cents"] >= 0
    assert isinstance(data["total_charge_cents"], int)
    assert data["total_charge_cents"] >= 0
    assert data["status"] in {
        "PENDING", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED",
    }


def assert_host_assignment(data: dict) -> None:
    _assert_common_full(data, "HostAssignment")
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["host_id"])
    assert isinstance(data["assigned_by_user_id"], str)
    assert data["assigned_by_user_id"]
    # approved_by_user_id is nullable until approval
    if data.get("approved_by_user_id") is not None:
        assert isinstance(data["approved_by_user_id"], str)
    assert data["status"] in {"PENDING_APPROVAL", "ACTIVE", "REVOKED", "REJECTED"}


def assert_self_exclusion(data: dict) -> None:
    """SelfExclusion is append-only — id + created_at only (PRD §2.4)."""
    _assert_common_append_only(data, "SelfExclusion")
    assert is_valid_uuid(data["member_id"])
    assert is_iso8601_timestamp(data["requested_at"])
    assert is_iso8601_timestamp(data["exclusion_until"])
    assert isinstance(data["reason"], str)
    assert data["status"] in {"ACTIVE", "REINSTATED", "EXPIRED"}


def assert_velocity_alert(data: dict) -> None:
    """VelocityAlert is append-only — id + created_at only (PRD §2.4)."""
    _assert_common_append_only(data, "VelocityAlert")
    assert is_valid_uuid(data["member_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["total_theoretical_loss_cents"], int)
    assert data["total_theoretical_loss_cents"] >= 0
    assert data["severity"] in {"FLAGGED", "SUSPENDED"}


def assert_annual_reset_run(data: dict) -> None:
    _assert_common_full(data, "AnnualResetRun")
    assert isinstance(data["reset_year"], int)
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert data["status"] in {"SCHEDULED", "EXECUTED", "CANCELLED"}
    assert isinstance(data["members_reset_count"], int)
    assert data["members_reset_count"] >= 0
    assert isinstance(data["tier_credits_lifetime_invariant_before_cents"], int)
    assert isinstance(data["tier_credits_lifetime_invariant_after_cents"], int)


# ─── Domain invariant checkers ────────────────────────────────────────────

def assert_lifetime_invariant_preserved(data: dict) -> None:
    """PRD §3.8: lifetime totals are never reset — before-and-after invariant
    captures sum(Member.tier_credits_lifetime) immediately before and after
    execute. The two values MUST be equal."""
    assert (
        data["tier_credits_lifetime_invariant_after_cents"]
        == data["tier_credits_lifetime_invariant_before_cents"]
    ), (
        "AnnualResetRun.tier_credits_lifetime_invariant_after_cents must equal "
        "tier_credits_lifetime_invariant_before_cents (lifetime is never reset)."
    )
