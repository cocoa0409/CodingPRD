"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Each factory provides sensible defaults and accepts
**overrides for the values a test needs to control.
"""

DEFAULTS = {
    "CENTER_NAME": "Test Center",
    "DEVICE_COUNT": 50,
    "RATIO": 10,
    "PROGRAM_NAME": "Test Program",
    "MIN_AGE": 4,
    "MAX_AGE": 18,
    "DROP_IN_FEE_CENTS": 4000,
    "BIRTH_DATE": "2016-01-01",   # age 10 at clock default 2026-04-01
    "SESSION_STARTS_AT": "2026-05-01T16:00:00Z",
    "SESSION_ENDS_AT": "2026-05-01T18:00:00Z",
    "SHOWCASE_STARTS_AT": "2026-05-11T09:00:00Z",
    "SHOWCASE_DEADLINE_AT": "2026-05-10T12:00:00Z",
}


def create_center_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CENTER_NAME"],
        "device_count": DEFAULTS["DEVICE_COUNT"],
        "min_student_instructor_ratio": DEFAULTS["RATIO"],
    }
    payload.update(overrides)
    return payload


# Mutable counter so distinct Program codes are minted automatically across a
# test that creates several programs (codes are unique per PRD §3.1).
_PROGRAM_CODE_SEQ = [0]


def _next_program_code() -> str:
    _PROGRAM_CODE_SEQ[0] += 1
    return f"PRG{_PROGRAM_CODE_SEQ[0]:03d}"


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "code": _next_program_code(),
        "min_age": DEFAULTS["MIN_AGE"],
        "max_age": DEFAULTS["MAX_AGE"],
        "drop_in_fee_cents": DEFAULTS["DROP_IN_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_belt_level_payload(program_id: str, rank: int = 1, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "name": f"Belt-{rank}",
        "rank": rank,
        "required_badge_count": 0,
    }
    payload.update(overrides)
    return payload


def create_badge_payload(belt_level_id: str, **overrides) -> dict:
    payload = {
        "belt_level_id": belt_level_id,
        "name": "Loops",
    }
    payload.update(overrides)
    return payload


_GUARDIAN_EMAIL_SEQ = [0]


def _next_guardian_email() -> str:
    _GUARDIAN_EMAIL_SEQ[0] += 1
    return f"guardian{_GUARDIAN_EMAIL_SEQ[0]:04d}@x.com"


def create_guardian_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Guardian",
        "email": _next_guardian_email(),
    }
    payload.update(overrides)
    return payload


def create_wallet_adjustment_payload(amount_cents: int, reason: str = "test", **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def create_member_payload(guardian_id: str, program_id: str, **overrides) -> dict:
    payload = {
        "guardian_id": guardian_id,
        "program_id": program_id,
        "full_name": "Test Member",
        "birth_date": DEFAULTS["BIRTH_DATE"],
    }
    payload.update(overrides)
    return payload


def create_membership_payload(member_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "monthly_fee_cents": 8000,
        "included_sessions_per_cycle": 8,
    }
    payload.update(overrides)
    return payload


def create_session_payload(center_id: str, program_id: str, **overrides) -> dict:
    payload = {
        "center_id": center_id,
        "program_id": program_id,
        "format": "AFTER_SCHOOL",
        "week_count": 1,
        "starts_at": DEFAULTS["SESSION_STARTS_AT"],
        "ends_at": DEFAULTS["SESSION_ENDS_AT"],
        "device_seats_requested": 1,
        "assigned_instructor_count": 5,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(session_id: str, member_id: str, expected_session_version: int,
                              coverage: str = "DROP_IN", **overrides) -> dict:
    payload = {
        "session_id": session_id,
        "member_id": member_id,
        "coverage": coverage,
        "expected_session_version": expected_session_version,
    }
    if coverage == "DROP_IN":
        payload["sibling_index"] = 1
    payload.update(overrides)
    return payload


def create_badge_award_payload(enrollment_id: str, badge_id: str, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "badge_id": badge_id,
    }
    payload.update(overrides)
    return payload


def create_showcase_payload(center_id: str, program_id: str, **overrides) -> dict:
    payload = {
        "center_id": center_id,
        "program_id": program_id,
        "min_belt_rank": 1,
        "capacity": 10,
        "starts_at": DEFAULTS["SHOWCASE_STARTS_AT"],
        "entry_deadline_at": DEFAULTS["SHOWCASE_DEADLINE_AT"],
    }
    payload.update(overrides)
    return payload


def create_showcase_entry_payload(showcase_id: str, member_id: str, **overrides) -> dict:
    payload = {
        "showcase_id": showcase_id,
        "member_id": member_id,
    }
    payload.update(overrides)
    return payload


def create_accept_payload(expected_showcase_version: int, **overrides) -> dict:
    payload = {"expected_showcase_version": expected_showcase_version}
    payload.update(overrides)
    return payload


def create_score_payload(score, **overrides) -> dict:
    payload = {"score": score}
    payload.update(overrides)
    return payload


def create_quote_payload(member_ids: list, **overrides) -> dict:
    payload = {"member_ids": member_ids}
    payload.update(overrides)
    return payload


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
