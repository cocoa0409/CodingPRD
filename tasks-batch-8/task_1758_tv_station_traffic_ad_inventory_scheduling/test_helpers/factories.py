"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_advertiser_payload(**overrides) -> dict:
    defaults = {
        "name": f"Advertiser {_seq()}",
        "product_category": "RETAIL",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "title": f"Program {_seq()}",
        "daypart_code": "DAYTIME",
        "airs_weekday": 1,
        "start_time_local": "13:00",
        "duration_minutes": 60,
        "rating_estimate": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_avail_week_payload(week_start_date: str = "2026-08-03", **overrides) -> dict:
    defaults = {"week_start_date": week_start_date}
    defaults.update(overrides)
    return defaults


def create_avail_unit_payload(
    program_id: str,
    air_date: str,
    total_seconds: int = TEST_DEFAULTS["TOTAL_SECONDS"],
    break_position: int = 1,
    reserved_political_seconds=None,
    **overrides,
) -> dict:
    """reserved_political_seconds is omitted entirely when None (PRD default: 0)."""
    defaults = {
        "program_id": program_id,
        "air_date": air_date,
        "break_position": break_position,
        "total_seconds": total_seconds,
    }
    if reserved_political_seconds is not None:
        defaults["reserved_political_seconds"] = reserved_political_seconds
    defaults.update(overrides)
    return defaults


def create_log_day_payload(log_date: str, **overrides) -> dict:
    defaults = {"log_date": log_date}
    defaults.update(overrides)
    return defaults


def create_order_payload(
    advertiser_id: str,
    flight_start_date: str = TEST_DEFAULTS["FLIGHT_START"],
    flight_end_date: str = TEST_DEFAULTS["FLIGHT_END"],
    **overrides,
) -> dict:
    defaults = {
        "advertiser_id": advertiser_id,
        "flight_start_date": flight_start_date,
        "flight_end_date": flight_end_date,
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(
    program_id: str,
    weeks_requested: int = 1,
    spots_per_week: int = 1,
    spot_length_seconds: int = 30,
    gross_rate_cents: int = TEST_DEFAULTS["GROSS_RATE_CENTS"],
    guaranteed_rating=0,
    **overrides,
) -> dict:
    defaults = {
        "program_id": program_id,
        "weeks_requested": weeks_requested,
        "spots_per_week": spots_per_week,
        "spot_length_seconds": spot_length_seconds,
        "gross_rate_cents": gross_rate_cents,
        "guaranteed_rating": guaranteed_rating,
    }
    defaults.update(overrides)
    return defaults


def create_copy_instruction_payload(
    advertiser_id: str,
    length_seconds: int = 30,
    rotation_weight=None,
    **overrides,
) -> dict:
    """rotation_weight is omitted entirely when None (PRD default: 1)."""
    defaults = {"advertiser_id": advertiser_id, "length_seconds": length_seconds}
    if rotation_weight is not None:
        defaults["rotation_weight"] = rotation_weight
    defaults.update(overrides)
    return defaults


def place_spot_payload(avail_unit_id: str, expected_avail_unit_version: int, **overrides) -> dict:
    defaults = {
        "avail_unit_id": avail_unit_id,
        "expected_avail_unit_version": expected_avail_unit_version,
    }
    defaults.update(overrides)
    return defaults


def preempt_payload(preempt_reason: str = "OVERSOLD", **overrides) -> dict:
    defaults = {"preempt_reason": preempt_reason}
    defaults.update(overrides)
    return defaults


def approve_order_payload(expected_order_version: int, **overrides) -> dict:
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


def as_run_entry(spot_id: str, aired: bool, actual_rating=None) -> dict:
    entry = {"spot_id": spot_id, "aired": aired}
    if actual_rating is not None:
        entry["actual_rating"] = actual_rating
    return entry


def reconcile_payload(entries) -> dict:
    return {"entries": entries}
