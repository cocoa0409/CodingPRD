"""Entity assertions and domain invariant checkers.

Each assert_* validates the system-managed fields (UUID id, ISO 8601
created_at/updated_at, integer version) plus the entity's enum fields
against the sets named in the PRD.
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_watch_group(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["precinct_code"], str)
    assert data["certification_status"] in (
        "UNCERTIFIED", "PROVISIONAL", "CERTIFIED", "SUSPENDED", "REVOKED",
    )
    assert data["posture"] in (
        "DORMANT", "FORMATION", "OPERATIONAL", "DEGRADED", "FROZEN",
    )
    assert isinstance(data["sign_inventory_count"], int)
    assert isinstance(data["materials_inventory_count"], int)
    assert isinstance(data["participation_score"], (int, float))


def assert_block(data: dict):
    _assert_common(data)
    assert isinstance(data["watch_group_id"], str)
    assert isinstance(data["street_segment"], str)
    assert isinstance(data["household_count"], int) and data["household_count"] >= 1
    assert data["registration_status"] in ("PENDING", "REGISTERED", "DEREGISTERED")
    assert isinstance(data["risk_heat_score"], (int, float))


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["watch_group_id"], str)
    assert isinstance(data["block_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["contact_channel"] in ("SMS", "EMAIL", "PHONE_TREE")
    assert data["roster_visibility"] in (
        "GROUP_ONLY", "LIAISON_VISIBLE", "PROGRAM_WIDE",
    )
    assert data["membership_status"] in ("ACTIVE", "SUSPENDED", "WITHDRAWN")
    assert isinstance(data["strike_count"], int) and data["strike_count"] >= 0


def assert_captain_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["block_id"], str)
    assert isinstance(data["member_id"], str)
    assert data["assignment_status"] in ("ACTIVE", "RELIEVED", "REVOKED")


def assert_incident_report(data: dict):
    _assert_common(data)
    assert isinstance(data["block_id"], str)
    assert isinstance(data["reporter_member_id"], str)
    assert data["category"] in (
        "SUSPICIOUS_ACTIVITY", "PROPERTY_CRIME", "VANDALISM",
        "NOISE", "TRAFFIC", "OTHER",
    )
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 5
    assert data["review_status"] in (
        "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO",
        "CORROBORATED", "DISMISSED", "CLEARED",
    )
    assert isinstance(data["corroboration_weight"], (int, float))
    assert isinstance(data["shared_with_liaison"], bool)


def assert_alert(data: dict):
    _assert_common(data)
    assert isinstance(data["watch_group_id"], str)
    assert data["alert_kind"] in (
        "INCIDENT_BULLETIN", "MEETING_NOTICE", "EVENT_NOTICE", "SAFETY_TIP",
    )
    assert data["audience_scope"] in ("BLOCK", "GROUP")
    assert data["distribution_status"] in ("DRAFT", "QUEUED", "SENT", "RECALLED")
    assert data["ack_posture"] in ("UNTRACKED", "PARTIAL", "MAJORITY", "FULL")
    assert isinstance(data["recipient_count"], int) and data["recipient_count"] >= 0
    assert isinstance(data["ack_count"], int) and data["ack_count"] >= 0


def assert_liaison_officer(data: dict):
    _assert_common(data)
    assert isinstance(data["badge_number"], str) and len(data["badge_number"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["precinct_code"], str)


def assert_liaison_meeting(data: dict):
    _assert_common(data)
    assert isinstance(data["watch_group_id"], str)
    assert isinstance(data["liaison_officer_id"], str)
    assert is_iso8601_timestamp(data["room_slot_start"])
    assert is_iso8601_timestamp(data["room_slot_end"])
    assert data["meeting_status"] in ("SCHEDULED", "HELD", "CANCELLED")
    assert isinstance(data["quorum_met"], bool)


def assert_data_share_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["watch_group_id"], str)
    assert isinstance(data["liaison_officer_id"], str)
    assert data["scope"] in ("INCIDENT_SUMMARIES", "ROSTER_CONTACTS", "FULL")
    assert data["agreement_status"] in ("PENDING", "ACTIVE", "REVOKED", "EXPIRED")
    assert is_iso8601_timestamp(data["expires_at"])


def assert_training_session(data: dict):
    _assert_common(data)
    assert isinstance(data["watch_group_id"], str)
    assert isinstance(data["trainer_officer_id"], str)
    assert data["curriculum"] in (
        "BIAS_AVOIDANCE", "OBSERVATION_SKILLS", "REPORT_WRITING",
    )
    assert data["session_status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_community_event(data: dict):
    _assert_common(data)
    assert isinstance(data["watch_group_id"], str)
    assert data["event_kind"] in ("NATIONAL_NIGHT_OUT", "BLOCK_PARTY", "SAFETY_FAIR")
    assert is_iso8601_timestamp(data["street_closure_start"])
    assert is_iso8601_timestamp(data["street_closure_end"])
    assert data["event_status"] in ("PROPOSED", "APPROVED", "COMPLETED", "CANCELLED")
    assert isinstance(data["estimated_attendance"], int)
    assert data["estimated_attendance"] >= 0


def assert_certification_review(data: dict):
    _assert_common(data)
    assert isinstance(data["watch_group_id"], str)
    assert isinstance(data["reviewing_officer_id"], str)
    assert data["review_status"] in ("PENDING", "APPROVED", "REJECTED", "CONDITIONAL")
    assert isinstance(data["certification_points"], (int, float))
    assert isinstance(data["certification_grant_months"], int)


def assert_group_invariants(data: dict):
    """Domain invariants that must hold after any watch-group operation."""
    assert data["sign_inventory_count"] >= 0, "sign ledger may never go negative"
    assert data["materials_inventory_count"] >= 0, (
        "materials ledger may never go negative"
    )
    assert data["participation_score"] >= 0
    if data["certification_status"] in ("UNCERTIFIED", "REVOKED"):
        assert data["certification_valid_until"] is None, (
            "certification_valid_until stays null while UNCERTIFIED or REVOKED"
        )
