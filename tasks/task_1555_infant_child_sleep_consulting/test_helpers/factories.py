"""Payload factories — one per entity, input fields only."""

DEFAULT_ANSWERS = {
    "night_wakings": 2,
    "night_feeds": 1,
    "bedtime_resistance_minutes": 30,
    "nap_total_minutes": 120,
    "medical_flags": False,
    "preterm_birth": False,
}


def create_consultant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dana Sleep",
        "certification_no": "CERT-000",
        "max_active_cases": 5,
    }
    defaults.update(overrides)
    return defaults


def register_family_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Fam Z",
        "email": "z@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(family_id, consultant_id, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "consultant_id": consultant_id,
        "child_birth_date": "2026-05-01",
        "delivery_mode": "ONE_ON_ONE",
        "guarantee_goal_night_wakings": 2,
    }
    defaults.update(overrides)
    return defaults


def submit_questionnaire_payload(answers=None, **overrides) -> dict:
    payload = {"answers": dict(answers or DEFAULT_ANSWERS)}
    payload.update(overrides)
    return payload


def review_questionnaire_payload(adjustment_points=0, **overrides) -> dict:
    payload = {"adjustment_points": adjustment_points}
    payload.update(overrides)
    return payload


def create_plan_payload(expected_case_version, **overrides) -> dict:
    defaults = {
        "method": "GENTLE_NO_CRY",
        "target_night_wake_count": 2,
        "target_longest_stretch_minutes": 240,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def purchase_package_payload(**overrides) -> dict:
    defaults = {
        "tier": "BASIC",
        "kind": "INITIAL",
        "starts_on": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def submit_log_payload(log_date="2026-08-01", **overrides) -> dict:
    defaults = {
        "log_date": log_date,
        "night_wake_count": 3,
        "longest_stretch_minutes": 120,
        "nap_count": 2,
        "nap_total_minutes": 130,
    }
    defaults.update(overrides)
    return defaults


def review_log_payload(outcome="ON_TRACK", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def book_session_payload(expected_package_version, **overrides) -> dict:
    defaults = {
        "session_type": "REGRESSION",
        "scheduled_start": "2026-08-10T10:00:00Z",
        "scheduled_end": "2026-08-10T11:00:00Z",
        "expected_package_version": expected_package_version,
    }
    defaults.update(overrides)
    return defaults


def send_message_payload(body="quick question", **overrides) -> dict:
    payload = {"body": body}
    payload.update(overrides)
    return payload


def respond_message_payload(response_body="answer", **overrides) -> dict:
    payload = {"response_body": response_body}
    payload.update(overrides)
    return payload


def create_refund_request_payload(refund_type="COOLING_OFF", **overrides) -> dict:
    payload = {"refund_type": refund_type}
    payload.update(overrides)
    return payload


def deny_refund_payload(denial_reason="not eligible", **overrides) -> dict:
    payload = {"denial_reason": denial_reason}
    payload.update(overrides)
    return payload


def create_course_payload(consultant_id, **overrides) -> dict:
    defaults = {
        "consultant_id": consultant_id,
        "title": "Newborn Sleep 101",
        "starts_on": "2026-09-01",
        "capacity": 2,
        "price_cents": 19900,
    }
    defaults.update(overrides)
    return defaults


def enroll_payload(case_id, **overrides) -> dict:
    payload = {"case_id": case_id}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
