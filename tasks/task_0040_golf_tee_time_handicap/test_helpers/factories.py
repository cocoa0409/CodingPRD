"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COURSE_NAME": "Test Course",
    "COURSE_RATING": 70.0,
    "SLOPE_RATING": 113,
    "PEAK_FEE_CENTS": 8000,
    "OFFPEAK_FEE_CENTS": 5000,
    "GOLFER_NAME": "Test Golfer",
}


def create_course_payload(**overrides) -> dict:
    """Course input fields. peak_start_hour/peak_end_hour/member_discount_pct optional."""
    defaults = {
        "name": DEFAULTS["COURSE_NAME"],
        "course_rating": DEFAULTS["COURSE_RATING"],
        "slope_rating": DEFAULTS["SLOPE_RATING"],
        "peak_fee_cents": DEFAULTS["PEAK_FEE_CENTS"],
        "offpeak_fee_cents": DEFAULTS["OFFPEAK_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_golfer_payload(**overrides) -> dict:
    """Golfer input fields. membership_tier optional (defaults PUBLIC server-side)."""
    defaults = {"full_name": DEFAULTS["GOLFER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_score_payload(golfer_id, course_id, played_on, adjusted_gross_score, **overrides) -> dict:
    defaults = {
        "golfer_id": golfer_id,
        "course_id": course_id,
        "played_on": played_on,
        "adjusted_gross_score": adjusted_gross_score,
    }
    defaults.update(overrides)
    return defaults


def create_tee_time_payload(course_id, start_utc, local_hour, group_type, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "start_utc": start_utc,
        "local_hour": local_hour,
        "group_type": group_type,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(golfer_id, expected_tee_time_version, **overrides) -> dict:
    defaults = {
        "golfer_id": golfer_id,
        "expected_tee_time_version": expected_tee_time_version,
    }
    defaults.update(overrides)
    return defaults


def create_handicap_revision_payload(effective_utc, **overrides) -> dict:
    defaults = {"effective_utc": effective_utc}
    defaults.update(overrides)
    return defaults
