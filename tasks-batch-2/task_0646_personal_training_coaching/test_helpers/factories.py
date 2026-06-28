"""Payload factories — one per resource, input fields only.

Each factory provides sensible PRD-consistent defaults and accepts **overrides
so tests can control just the values they care about. Required fields with no
universal default (foreign keys, versions, time windows) are explicit
parameters.
"""
import itertools

# Monotonic counter so factory-minted emails are unique within a single test
# (the email uniqueness constraint spans Trainer and Client respectively).
_EMAIL_SEQ = itertools.count(1)


def _unique_email(prefix: str) -> str:
    return f"{prefix}{next(_EMAIL_SEQ)}@example.com"


def create_trainer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Trainer",
        "email": _unique_email("trainer"),
    }
    payload.update(overrides)
    return payload


def create_client_payload(trainer_id, **overrides) -> dict:
    payload = {
        "trainer_id": trainer_id,
        "full_name": "Test Client",
        "email": _unique_email("client"),
        "sex": "MALE",
        "birth_year": 1992,
        "height_cm": 178,
    }
    payload.update(overrides)
    return payload


def create_engagement_payload(client_id, expected_client_version,
                              billing_model="SESSION_PACK", **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "billing_model": billing_model,
        "expected_client_version": expected_client_version,
    }
    payload.update(overrides)
    return payload


def create_session_pack_payload(total_sessions=5, price_cents=50000, **overrides) -> dict:
    payload = {
        "total_sessions": total_sessions,
        "price_cents": price_cents,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(engagement_id, start_utc, end_utc,
                           session_pack_id=None, expected_session_pack_version=None,
                           **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    if session_pack_id is not None:
        payload["session_pack_id"] = session_pack_id
    if expected_session_pack_version is not None:
        payload["expected_session_pack_version"] = expected_session_pack_version
    payload.update(overrides)
    return payload


def create_program_assignment_payload(engagement_id, title="Phase 1",
                                      planned_workouts_per_week=4,
                                      habit_checks_target=10, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "title": title,
        "planned_workouts_per_week": planned_workouts_per_week,
        "habit_checks_target": habit_checks_target,
    }
    payload.update(overrides)
    return payload


def create_macro_plan_payload(goal="FAT_LOSS", activity_level="MODERATE", **overrides) -> dict:
    payload = {
        "goal": goal,
        "activity_level": activity_level,
    }
    payload.update(overrides)
    return payload


def create_check_in_payload(measured_at, weight_kg, window_start_utc, window_end_utc,
                            **overrides) -> dict:
    payload = {
        "measured_at": measured_at,
        "weight_kg": weight_kg,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    payload.update(overrides)
    return payload


def resubmit_check_in_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_habit_log_payload(engagement_id, program_assignment_id, kind, logged_at,
                             **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "program_assignment_id": program_assignment_id,
        "kind": kind,
        "logged_at": logged_at,
    }
    payload.update(overrides)
    return payload


def create_message_payload(engagement_id, body="Hi coach", **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "body": body,
    }
    payload.update(overrides)
    return payload


def invoice_payload(line_items, **overrides) -> dict:
    payload = {"line_items": line_items}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
