"""Payload factories — one per entity, input fields only.

Each factory builds a minimal valid create payload; pass ``**overrides`` to vary
fields under test. Factories that reference a parent require the parent id be
supplied via overrides (the fixtures layer threads real ids).
"""

DEFAULTS = {
    "PRODUCTION_TITLE": "Test Production",
    "TOTAL_BUDGET_CENTS": 1_000_000,
    "ESTIMATED_CENTS": 500_000,
    "DAILY_RATE_CENTS": 100_000,
    "PAGE_EIGHTHS": 8,
    "FRINGE_RATE_BPS": 1800,
    "FRINGE_FLAT_CENTS": 15_000,
    "GROSS_RECEIPTS_CENTS": 80_000_000,
}


def create_production_payload(**overrides) -> dict:
    payload = {
        "title": DEFAULTS["PRODUCTION_TITLE"],
        "production_type": "FEATURE",
        "total_budget_cents": DEFAULTS["TOTAL_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_budget_line_payload(production_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "category": "BELOW_THE_LINE_LABOR",
        "estimated_cents": DEFAULTS["ESTIMATED_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_shooting_day_payload(production_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "shoot_date": "2026-07-01",
        "day_number": 1,
    }
    payload.update(overrides)
    return payload


def create_scene_payload(production_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "scene_number": "1A",
        "page_eighths": DEFAULTS["PAGE_EIGHTHS"],
        "int_ext": "INT",
        "day_night": "DAY",
    }
    payload.update(overrides)
    return payload


def create_crew_member_payload(production_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "full_name": "Test Crew",
        "role_title": "Grip",
        "daily_rate_cents": DEFAULTS["DAILY_RATE_CENTS"],
        "is_sag_aftra": False,
        "union_code": "NONE",
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(shooting_day_id, crew_member_id, expected_shooting_day_version, **overrides) -> dict:
    payload = {
        "shooting_day_id": shooting_day_id,
        "crew_member_id": crew_member_id,
        "call_time": "2026-07-01T06:00:00.000Z",
        "expected_shooting_day_version": expected_shooting_day_version,
    }
    payload.update(overrides)
    return payload


def check_out_payload(wrap_time, **overrides) -> dict:
    payload = {"wrap_time": wrap_time, "meal_breaks_taken": 0}
    payload.update(overrides)
    return payload


def create_call_sheet_payload(shooting_day_id, **overrides) -> dict:
    payload = {
        "shooting_day_id": shooting_day_id,
        "general_call_time": "2026-07-01T06:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_location_payload(production_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "name": "Test Location",
        "address": "1 Main St",
    }
    payload.update(overrides)
    return payload


def create_location_permit_payload(location_id, **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "permit_number": "P-1",
        "window_start": "2026-08-01T12:00:00.000Z",
        "window_end": "2026-08-01T16:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_residual_event_payload(production_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "market": "THEATRICAL",
        "gross_receipts_cents": DEFAULTS["GROSS_RECEIPTS_CENTS"],
        "event_date": "2026-01-31",
    }
    payload.update(overrides)
    return payload


def create_union_fringe_payload(production_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "union_code": "SAG_AFTRA",
        "fringe_rate_bps": DEFAULTS["FRINGE_RATE_BPS"],
        "pension_health_flat_cents": DEFAULTS["FRINGE_FLAT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_dailies_payload(shooting_day_id, **overrides) -> dict:
    payload = {
        "shooting_day_id": shooting_day_id,
        "reel_label": "A001",
    }
    payload.update(overrides)
    return payload


def flag_dailies_payload(**overrides) -> dict:
    payload = {"flagged_reason": "soft focus"}
    payload.update(overrides)
    return payload
