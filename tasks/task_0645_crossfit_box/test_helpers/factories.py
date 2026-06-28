"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def create_unlimited_plan_payload(**overrides) -> dict:
    """UNLIMITED plan: punch_count must be omitted/null."""
    defaults = {
        "name": "Unlimited Monthly",
        "plan_type": "UNLIMITED",
        "monthly_fee_cents": 12000,
        "commitment_months": 0,
        "early_termination_fee_cents": 0,
        "requires_foundations": False,
    }
    defaults.update(overrides)
    return defaults


def create_punch_plan_payload(**overrides) -> dict:
    """PUNCH plan: punch_count required (>= 1)."""
    defaults = {
        "name": "Punch Pack",
        "plan_type": "PUNCH",
        "monthly_fee_cents": 0,
        "punch_count": 5,
        "commitment_months": 0,
        "early_termination_fee_cents": 0,
        "requires_foundations": False,
    }
    defaults.update(overrides)
    return defaults


def register_member_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email("member"),
        "full_name": "Test Member",
        "home_box_member": True,
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(member_id: str, plan_id: str, **overrides) -> dict:
    defaults = {"member_id": member_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def create_coach_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Coach",
        "email": _unique_email("coach"),
        "certified": True,
    }
    defaults.update(overrides)
    return defaults


def create_program_track_payload(head_coach_id: str, **overrides) -> dict:
    defaults = {
        "name": "WOD Track",
        "track_type": "REGULAR",
        "head_coach_id": head_coach_id,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(track_id: str, coach_id: str, starts_at: str, **overrides) -> dict:
    defaults = {
        "track_id": track_id,
        "coach_id": coach_id,
        "starts_at": starts_at,
        "duration_minutes": 60,
        "capacity": 5,
        "drop_in_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(session_id, member_id, reservation_kind,
                               expected_session_version, membership_id=None,
                               **overrides) -> dict:
    payload = {
        "session_id": session_id,
        "member_id": member_id,
        "reservation_kind": reservation_kind,
        "expected_session_version": expected_session_version,
    }
    if membership_id is not None:
        payload["membership_id"] = membership_id
    payload.update(overrides)
    return payload


def create_benchmark_result_payload(member_id: str, benchmark_name: str,
                                    metric_kind: str, value, recorded_at: str,
                                    **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "benchmark_name": benchmark_name,
        "metric_kind": metric_kind,
        "value": value,
        "recorded_at": recorded_at,
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(captain_member_id: str, **overrides) -> dict:
    defaults = {
        "name": f"Team {uuid.uuid4().hex[:8]}",
        "captain_member_id": captain_member_id,
        "max_roster_size": 4,
    }
    defaults.update(overrides)
    return defaults


def create_team_member_payload(team_id: str, member_id: str, **overrides) -> dict:
    defaults = {"team_id": team_id, "member_id": member_id}
    defaults.update(overrides)
    return defaults
