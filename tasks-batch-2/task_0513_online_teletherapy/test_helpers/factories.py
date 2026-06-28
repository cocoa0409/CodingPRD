"""Payload factories — one per create/transition endpoint, input fields only.

Each factory returns the minimal valid body and accepts **overrides so
individual tests can control the values that matter. Field names are PRD-exact.
"""

DEFAULTS = {
    "STATE_CODE": "CA",
    "SEVERITY_SCORE": 3,
    "SPECIALTIES": ["ANXIETY"],
    "PRESENTING_CONCERNS": ["ANXIETY"],
    "LICENSE_EXPIRES_ON": "2027-01-01T00:00:00Z",
    "BASE_WEEKLY_FEE_CENTS": 9900,
}

# Monotonic suffix so default emails stay unique within a test run.
_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_client_payload(**overrides) -> dict:
    defaults = {
        "email": f"client{_next()}@example.com",
        "full_name": "Test Client",
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def submit_intake_payload(**overrides) -> dict:
    defaults = {
        "presenting_concerns": list(DEFAULTS["PRESENTING_CONCERNS"]),
        "severity_score": DEFAULTS["SEVERITY_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_therapist_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Therapist",
        "specialties": list(DEFAULTS["SPECIALTIES"]),
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(state_code=None, expires_on=None, **overrides) -> dict:
    defaults = {
        "state_code": state_code if state_code is not None else DEFAULTS["STATE_CODE"],
        "expires_on": expires_on if expires_on is not None else DEFAULTS["LICENSE_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_match_payload(client_id, therapist_id, **overrides) -> dict:
    defaults = {"client_id": client_id, "therapist_id": therapist_id}
    defaults.update(overrides)
    return defaults


def request_switch_payload(switch_reason="FIT", **overrides) -> dict:
    defaults = {"switch_reason": switch_reason}
    defaults.update(overrides)
    return defaults


def schedule_live_session_payload(starts_at, ends_at, expected_match_version, **overrides) -> dict:
    defaults = {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "expected_match_version": expected_match_version,
    }
    defaults.update(overrides)
    return defaults


def post_message_payload(body="hello", **overrides) -> dict:
    defaults = {"body": body}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(client_id, **overrides) -> dict:
    defaults = {"client_id": client_id}
    defaults.update(overrides)
    return defaults


def pause_subscription_payload(resume_on, expected_subscription_version, **overrides) -> dict:
    defaults = {
        "resume_on": resume_on,
        "expected_subscription_version": expected_subscription_version,
    }
    defaults.update(overrides)
    return defaults


def create_crisis_escalation_payload(severity="ACUTE", **overrides) -> dict:
    defaults = {"severity": severity}
    defaults.update(overrides)
    return defaults


def create_financial_aid_payload(annual_income_cents, household_size, **overrides) -> dict:
    defaults = {
        "annual_income_cents": annual_income_cents,
        "household_size": household_size,
    }
    defaults.update(overrides)
    return defaults


def create_superbill_payload(period_start, period_end, **overrides) -> dict:
    defaults = {"period_start": period_start, "period_end": period_end}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
