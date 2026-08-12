"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "DISTRIBUTOR_NAME": "Distro Co",
    "TERRITORY": "US",
    "FILM_TITLE": "Indie Feature",
    "GENRE": "NARRATIVE",
    "RUNTIME_MINUTES": 100,
    "RATING": "R",
    "RELEASE_PATTERN": "LIMITED",
    "TARGET_RELEASE_DATE": "2026-05-01T00:00:00Z",
    "MIN_SCREENS_FOR_WIDE": 0,
    "MARKET_CODE": "NYC",
    "POPULATION_TIER": "TIER_1",
    "WEEKLY_COOP_BUDGET_CENTS": 100000,
    "THEATRE_NAME": "Theatre One",
    "CIRCUIT": "Alamo",
    "HOUSE_ALLOWANCE_CENTS": 100,
    "AUDITORIUM_LABEL": "Auditorium 1",
    "SEAT_COUNT": 200,
    "PROJECTION_FORMAT": "DCP_2K",
    "OPENING_DATE": "2026-05-01T00:00:00Z",
    "MIN_WEEKS_COMMITTED": 1,
    "WEEK_ONE_RENTAL_PCT": 0.60,
    "RENTAL_DECAY_PER_WEEK": 0.05,
    "FLOOR_PCT": 0.30,
    "PER_CAPITA_FLOOR_CENTS": 100,
    "AGGREGATE_RENTAL_PCT": 0.50,
    "AGGREGATE_MIN_SCREENS": 2,
    "AGGREGATE_HOUSE_ALLOWANCE_CENTS": 200000,
    "CONTENT_FORMAT": "DCP_2K",
    "TRACKING_NUMBER": "TN-0001",
    "KDM_VALID_FROM": "2026-05-01T00:00:00Z",
    "KDM_VALID_UNTIL": "2026-07-31T00:00:00Z",
    "SCREEN_CERT_FINGERPRINT": "FP-1",
    "REPORT_DATE": "2026-05-01T00:00:00Z",
    "GROSS_CENTS": 500000,
    "ADMISSIONS": 2000,
    "COMMITTED_CENTS": 100000,
    "COOP_SHARE_PCT": 0.50,
    "CLEARANCE_RADIUS_KM": 5.0,
    "EFFECTIVE_FROM": "2026-06-01T00:00:00Z",
    "EFFECTIVE_UNTIL": "2026-06-30T00:00:00Z",
    "WINDOW_KIND": "SVOD",
    "SCHEDULED_START": "2026-08-01T00:00:00Z",
    "HOLDOVER_RATIONALE": "Strong week; extend the engagement",
}


def create_distributor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DISTRIBUTOR_NAME"],
        "territory": DEFAULTS["TERRITORY"],
    }
    defaults.update(overrides)
    return defaults


def create_film_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["FILM_TITLE"],
        "genre": DEFAULTS["GENRE"],
        "runtime_minutes": DEFAULTS["RUNTIME_MINUTES"],
        "rating": DEFAULTS["RATING"],
        "release_pattern": DEFAULTS["RELEASE_PATTERN"],
        "target_release_date": DEFAULTS["TARGET_RELEASE_DATE"],
        "min_screens_for_wide": DEFAULTS["MIN_SCREENS_FOR_WIDE"],
    }
    defaults.update(overrides)
    return defaults


def create_market_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["MARKET_CODE"],
        "population_tier": DEFAULTS["POPULATION_TIER"],
        "weekly_coop_budget_cents": DEFAULTS["WEEKLY_COOP_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_theatre_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["THEATRE_NAME"],
        "circuit": DEFAULTS["CIRCUIT"],
        "market_code": DEFAULTS["MARKET_CODE"],
        "house_allowance_cents": DEFAULTS["HOUSE_ALLOWANCE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_screen_payload(**overrides) -> dict:
    defaults = {
        "auditorium_label": DEFAULTS["AUDITORIUM_LABEL"],
        "seat_count": DEFAULTS["SEAT_COUNT"],
        "projection_format": DEFAULTS["PROJECTION_FORMAT"],
    }
    defaults.update(overrides)
    return defaults


def create_aggregate_deal_payload(film_id: str, **overrides) -> dict:
    defaults = {
        "film_id": film_id,
        "circuit": DEFAULTS["CIRCUIT"],
        "aggregate_rental_pct": DEFAULTS["AGGREGATE_RENTAL_PCT"],
        "min_screens": DEFAULTS["AGGREGATE_MIN_SCREENS"],
        "aggregate_house_allowance_cents": DEFAULTS["AGGREGATE_HOUSE_ALLOWANCE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_agreement_payload(film_id: str, theatre_id: str, screen_id: str, **overrides) -> dict:
    defaults = {
        "film_id": film_id,
        "theatre_id": theatre_id,
        "screen_id": screen_id,
        "opening_date": DEFAULTS["OPENING_DATE"],
        "min_weeks_committed": DEFAULTS["MIN_WEEKS_COMMITTED"],
        "week_one_rental_pct": DEFAULTS["WEEK_ONE_RENTAL_PCT"],
        "rental_decay_per_week": DEFAULTS["RENTAL_DECAY_PER_WEEK"],
        "floor_pct": DEFAULTS["FLOOR_PCT"],
        "per_capita_floor_cents": DEFAULTS["PER_CAPITA_FLOOR_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_dcp_shipment_payload(**overrides) -> dict:
    defaults = {
        "content_format": DEFAULTS["CONTENT_FORMAT"],
        "tracking_number": DEFAULTS["TRACKING_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_kdm_key_payload(**overrides) -> dict:
    defaults = {
        "valid_from_utc": DEFAULTS["KDM_VALID_FROM"],
        "valid_until_utc": DEFAULTS["KDM_VALID_UNTIL"],
        "screen_cert_fingerprint": DEFAULTS["SCREEN_CERT_FINGERPRINT"],
    }
    defaults.update(overrides)
    return defaults


def create_box_office_report_payload(**overrides) -> dict:
    defaults = {
        "report_date": DEFAULTS["REPORT_DATE"],
        "gross_cents": DEFAULTS["GROSS_CENTS"],
        "admissions": DEFAULTS["ADMISSIONS"],
    }
    defaults.update(overrides)
    return defaults


def create_marketing_commitment_payload(film_id: str, **overrides) -> dict:
    defaults = {
        "film_id": film_id,
        "committed_cents": DEFAULTS["COMMITTED_CENTS"],
        "coop_share_pct": DEFAULTS["COOP_SHARE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_zone_clearance_payload(film_id: str, theatre_id: str, **overrides) -> dict:
    defaults = {
        "film_id": film_id,
        "theatre_id": theatre_id,
        "clearance_radius_km": DEFAULTS["CLEARANCE_RADIUS_KM"],
        "effective_from_utc": DEFAULTS["EFFECTIVE_FROM"],
        "effective_until_utc": DEFAULTS["EFFECTIVE_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_ancillary_window_payload(**overrides) -> dict:
    defaults = {
        "window_kind": DEFAULTS["WINDOW_KIND"],
        "scheduled_start_utc": DEFAULTS["SCHEDULED_START"],
    }
    defaults.update(overrides)
    return defaults
