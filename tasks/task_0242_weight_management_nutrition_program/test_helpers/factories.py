"""Payload factories — one per entity, input fields only.

Each factory builds a minimal valid create/transition payload and accepts
``**overrides`` to control the fields a given test needs to pin.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="user"):
    """Return a process-unique email to avoid duplicate-email collisions."""
    return f"{prefix}{next(_email_counter)}@example.com"


def create_program_payload(**overrides) -> dict:
    payload = {"name": "Test Program"}
    payload.update(overrides)
    return payload


def clock_set_payload(to_iso8601, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def create_plan_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "tier": "COACHING",
        "name": "Test Plan",
        "monthly_fee_cents": 6000,
    }
    payload.update(overrides)
    return payload


def create_member_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "full_name": "Test Member",
        "email": overrides.pop("email", unique_email("member")),
        "height_cm": 170,
    }
    payload.update(overrides)
    return payload


def create_coach_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "full_name": "Test Coach",
        "email": overrides.pop("email", unique_email("coach")),
    }
    payload.update(overrides)
    return payload


def create_intake_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "weight_kg": 95,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(member_id, plan_id, intake_assessment_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "plan_id": plan_id,
        "intake_assessment_id": intake_assessment_id,
    }
    payload.update(overrides)
    return payload


def create_weighin_payload(enrollment_id, weight_kg, expected_enrollment_version, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "weight_kg": weight_kg,
        "counts": True,
        "expected_enrollment_version": expected_enrollment_version,
    }
    payload.update(overrides)
    return payload


def create_goal_payload(enrollment_id, kind, target_weight_kg, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "kind": kind,
        "target_weight_kg": target_weight_kg,
    }
    payload.update(overrides)
    return payload


def create_milestone_payload(goal_id, threshold_pct, **overrides) -> dict:
    payload = {
        "goal_id": goal_id,
        "threshold_pct": threshold_pct,
    }
    payload.update(overrides)
    return payload


def create_coach_assignment_payload(enrollment_id, coach_id, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "coach_id": coach_id,
    }
    payload.update(overrides)
    return payload


def create_message_thread_payload(coach_assignment_id, **overrides) -> dict:
    payload = {
        "coach_assignment_id": coach_assignment_id,
        "subject": "Test Thread",
    }
    payload.update(overrides)
    return payload


def post_message_payload(body="Hello there", **overrides) -> dict:
    payload = {"body": body}
    payload.update(overrides)
    return payload


def create_eligibility_payload(member_id, enrollment_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "enrollment_id": enrollment_id,
    }
    payload.update(overrides)
    return payload


def create_rx_payload(enrollment_id, eligibility_determination_id, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "eligibility_determination_id": eligibility_determination_id,
    }
    payload.update(overrides)
    return payload


def issue_rx_payload(expected_enrollment_version, **overrides) -> dict:
    payload = {"expected_enrollment_version": expected_enrollment_version}
    payload.update(overrides)
    return payload
