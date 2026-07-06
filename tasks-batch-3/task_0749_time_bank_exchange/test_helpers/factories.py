"""Payload factories — one per entity, input fields only."""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def member_payload(**overrides) -> dict:
    defaults = {
        "email": f"{_uniq('m')}@example.com",
        "display_name": "Test Member",
        "home_neighborhood": "NW-01",
    }
    defaults.update(overrides)
    return defaults


def admin_adjust_payload(member_id: str, delta_minutes: int, memo: str = "test seed") -> dict:
    return {
        "member_id": member_id,
        "delta_minutes": delta_minutes,
        "memo": memo,
    }


def skill_offer_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "skill_code": "GARDENING",
        "title": "Gardening help",
        "minutes_per_session": 60,
    }
    defaults.update(overrides)
    return defaults


def skill_request_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "skill_code": "GARDENING",
        "needed_minutes": 60,
        "earliest_start_utc": "2026-03-05T10:00:00Z",
        "latest_start_utc": "2026-03-05T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def exchange_payload(offer_id: str, request_id: str, **overrides) -> dict:
    defaults = {
        "offer_id": offer_id,
        "request_id": request_id,
        "scheduled_start_utc": "2026-03-05T10:00:00Z",
        "committed_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def redemption_payload(member_id: str, expected_member_version: int,
                       reward_code: str = "FARMERS_MARKET_15") -> dict:
    return {
        "member_id": member_id,
        "reward_code": reward_code,
        "expected_member_version": expected_member_version,
    }


def credential_payload(subject_member_id: str, verifier_member_id: str, **overrides) -> dict:
    defaults = {
        "subject_member_id": subject_member_id,
        "verifier_member_id": verifier_member_id,
        "credential_type": "ID_CHECK",
        "evidence_url": "https://ev/1",
    }
    defaults.update(overrides)
    return defaults


def group_project_payload(organizer_member_id: str, **overrides) -> dict:
    defaults = {
        "organizer_member_id": organizer_member_id,
        "title": "Community project",
        "window_start_utc": "2026-03-05T09:00:00Z",
        "window_end_utc": "2026-03-05T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def project_shift_payload(**overrides) -> dict:
    defaults = {
        "role_label": "PACKER",
        "shift_start_utc": "2026-03-05T09:00:00Z",
        "duration_minutes": 60,
        "capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def dispute_payload(exchange_id: str, raised_by_member_id: str, **overrides) -> dict:
    defaults = {
        "exchange_id": exchange_id,
        "raised_by_member_id": raised_by_member_id,
        "reason_code": "INCOMPLETE_SERVICE",
        "claimed_delta_minutes": 15,
    }
    defaults.update(overrides)
    return defaults


def dispute_resolve_payload(outcome: str, admin_notes: str = "") -> dict:
    payload = {"outcome": outcome}
    if admin_notes:
        payload["admin_notes"] = admin_notes
    return payload


def impact_report_payload(report_month: str) -> dict:
    return {"report_month": report_month}
