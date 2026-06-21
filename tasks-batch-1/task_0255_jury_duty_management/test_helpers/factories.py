"""Payload factories — one per write endpoint, input fields only.

Field names are PRD-exact. Defaults match the pay configuration the difficulty
and corner recipes assume (daily 4000c, half 2000c, full_day_hours 6.0,
mileage 25 c/mi, pay_day_cap 3).
"""

DEFAULTS = {
    "TERM_NAME": "Test Term",
    "REPORT_DATE": "2026-07-01T00:00:00Z",
    "DAILY_PAY_CENTS": 4000,
    "HALF_DAY_PAY_CENTS": 2000,
    "FULL_DAY_HOURS": 6.0,
    "MILEAGE_RATE_CENTS": 25,
    "PAY_DAY_CAP": 3,
    "JUROR_NAME": "Test Juror",
    "BIRTH_YEAR": 1990,
    "ROUND_TRIP_MILES": 3.0,
    "TRIAL_CAPTION": "State v. Test",
}


def create_service_term_payload(**overrides) -> dict:
    """ServiceTerm input fields. fta_disqualify_threshold is optional (defaults to 3)."""
    payload = {
        "name": DEFAULTS["TERM_NAME"],
        "report_date": DEFAULTS["REPORT_DATE"],
        "daily_pay_cents": DEFAULTS["DAILY_PAY_CENTS"],
        "half_day_pay_cents": DEFAULTS["HALF_DAY_PAY_CENTS"],
        "full_day_hours": DEFAULTS["FULL_DAY_HOURS"],
        "mileage_rate_cents": DEFAULTS["MILEAGE_RATE_CENTS"],
        "pay_day_cap": DEFAULTS["PAY_DAY_CAP"],
    }
    payload.update(overrides)
    return payload


def create_juror_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["JUROR_NAME"],
        "birth_year": DEFAULTS["BIRTH_YEAR"],
        "round_trip_miles": DEFAULTS["ROUND_TRIP_MILES"],
    }
    payload.update(overrides)
    return payload


def draw_payload(count, expected_service_term_version, **overrides) -> dict:
    payload = {
        "count": count,
        "expected_service_term_version": expected_service_term_version,
    }
    payload.update(overrides)
    return payload


def qualification_payload(
    is_citizen=True, is_resident=True, felony_conviction=False, english_proficient=True,
    **overrides,
) -> dict:
    """QualificationResponse input — four boolean affirmations. Defaults qualify."""
    payload = {
        "is_citizen": is_citizen,
        "is_resident": is_resident,
        "felony_conviction": felony_conviction,
        "english_proficient": english_proficient,
    }
    payload.update(overrides)
    return payload


def check_in_payload(service_date, on_floor_hours, **overrides) -> dict:
    payload = {
        "service_date": service_date,
        "on_floor_hours": on_floor_hours,
    }
    payload.update(overrides)
    return payload


def disposition_payload(kind, reason_code, requested_term_id=None, **overrides) -> dict:
    """Disposition input. requested_term_id required for DEFER, null otherwise."""
    payload = {
        "kind": kind,
        "reason_code": reason_code,
    }
    if requested_term_id is not None:
        payload["requested_term_id"] = requested_term_id
    payload.update(overrides)
    return payload


def decide_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_trial_payload(caption=None, required_jurors=1, **overrides) -> dict:
    payload = {
        "caption": caption or DEFAULTS["TRIAL_CAPTION"],
        "required_jurors": required_jurors,
    }
    payload.update(overrides)
    return payload


def create_panel_payload(target_size=None, **overrides) -> dict:
    """Panel input. target_size optional (defaults to Trial.required_jurors)."""
    payload = {}
    if target_size is not None:
        payload["target_size"] = target_size
    payload.update(overrides)
    return payload


def seat_payload(summons_id, expected_panel_version, **overrides) -> dict:
    payload = {
        "summons_id": summons_id,
        "expected_panel_version": expected_panel_version,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
