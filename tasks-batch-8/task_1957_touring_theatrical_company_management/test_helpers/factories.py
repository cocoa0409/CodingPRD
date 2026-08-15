"""Payload factories — one per entity, input fields only (PRD §3 narratives)."""
from .constants import TEST_DEFAULTS


def create_tour_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["TOUR_NAME"],
        "budget_total_cents": TEST_DEFAULTS["BUDGET_TOTAL_CENTS"],
        "capitalization_cents": TEST_DEFAULTS["CAPITALIZATION_CENTS"],
        "per_diem_policy": "FULL_WEEK",
        "per_diem_daily_cents": TEST_DEFAULTS["PER_DIEM_DAILY_CENTS"],
        "royalty_tier_threshold_cents": TEST_DEFAULTS["ROYALTY_TIER_THRESHOLD_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["VENUE_NAME"],
        "city": TEST_DEFAULTS["VENUE_CITY"],
        "stage_width_ft": TEST_DEFAULTS["STAGE_WIDTH_FT"],
        "fly_capacity_lines": TEST_DEFAULTS["FLY_CAPACITY_LINES"],
        "power_amps": TEST_DEFAULTS["POWER_AMPS"],
        "crew_available": TEST_DEFAULTS["CREW_AVAILABLE"],
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(venue_id, expected_tour_version, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "play_week_start": TEST_DEFAULTS["PLAY_WEEK_START"],
        "play_week_end": TEST_DEFAULTS["PLAY_WEEK_END"],
        "load_in_date": TEST_DEFAULTS["LOAD_IN_DATE"],
        "travel_in_days": TEST_DEFAULTS["TRAVEL_IN_DAYS"],
        "guarantee_cents": TEST_DEFAULTS["GUARANTEE_CENTS"],
        "split_pct": TEST_DEFAULTS["SPLIT_PCT"],
        "expected_tour_version": expected_tour_version,
    }
    defaults.update(overrides)
    return defaults


def amend_stop_payload(expected_stop_version, **term_overrides) -> dict:
    payload = {"expected_stop_version": expected_stop_version}
    payload.update(term_overrides)
    return payload


def create_tech_check_payload(**overrides) -> dict:
    defaults = {
        "item": "STAGE_WIDTH_FT",
        "required_value": 40,
    }
    defaults.update(overrides)
    return defaults


def create_performance_payload(**overrides) -> dict:
    defaults = {
        "perf_date": TEST_DEFAULTS["PERF_DATE"],
        "curtain_time": TEST_DEFAULTS["CURTAIN_TIME"],
        "duration_minutes": TEST_DEFAULTS["DURATION_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def settlement_figures_payload(audited_gross_cents, taxes_cents, levies_cents) -> dict:
    return {
        "audited_gross_cents": audited_gross_cents,
        "taxes_cents": taxes_cents,
        "levies_cents": levies_cents,
    }


def create_cast_member_payload(**overrides) -> dict:
    defaults = {
        "name": "Pat Performer",
        "contract_type": "PRINCIPAL",
        "weekly_salary_cents": TEST_DEFAULTS["WEEKLY_SALARY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_track_payload(**overrides) -> dict:
    defaults = {
        "track_name": "Lead",
        "required_covers": 1,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_payload(cast_member_id, **overrides) -> dict:
    defaults = {
        "cast_member_id": cast_member_id,
        "kind": "UNDERSTUDY",
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_injury_payload(**overrides) -> dict:
    defaults = {"notes": "injury reported"}
    defaults.update(overrides)
    return defaults


def create_per_diem_payload(cast_member_id, **overrides) -> dict:
    defaults = {
        "cast_member_id": cast_member_id,
        "days_present": 7,
        "travel_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_crew_call_payload(**overrides) -> dict:
    defaults = {
        "call_type": "LOAD_IN",
        "scheduled_start": "2026-09-05T08:00:00Z",
        "lines": [
            {"position": "carpenter", "rate_cents_per_hour": TEST_DEFAULTS["CREW_RATE_CENTS_PER_HOUR"]},
        ],
    }
    defaults.update(overrides)
    return defaults


def crew_actual_lines(*position_hours) -> list:
    """Build actual_lines entries: crew_actual_lines(("carpenter", 8), ...)."""
    return [{"position": pos, "hours_worked": hrs} for pos, hrs in position_hours]
