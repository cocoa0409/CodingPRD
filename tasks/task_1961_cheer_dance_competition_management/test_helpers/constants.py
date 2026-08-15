"""Domain thresholds and numeric constants from the PRD.

Scoring (PRD scoring-model section): category weights, scale factor, trim
panel minimum, provisional minimum sheet count, score floor.
Pricing (PRD spectator-ticketing section): advance/gate prices, group
discount, hold minutes, per-order maximum, advance cutoff.
Geometry (PRD scheduling section): transition buffer and rest seconds.
Appeals/bids (PRD scores-appeals and bids sections): appeal window, bid
acceptance hours, at-large percentage.
"""

SCORING = {
    "WEIGHT_BUILDING_DIFFICULTY": 0.30,
    "WEIGHT_BUILDING_EXECUTION": 0.30,
    "WEIGHT_TUMBLING_DIFFICULTY": 0.20,
    "WEIGHT_OVERALL_IMPRESSION": 0.20,
    "SCORE_SCALE": 10,
    "TRIM_MIN_PANEL": 5,
    "PROVISIONAL_MIN_SHEETS": 2,
    "FLOOR": 0,
}

PRICING = {
    "ADVANCE_PRICE_CENTS": 1295,
    "GATE_PRICE_CENTS": 1895,
    "GROUP_MIN_QTY": 20,
    "GROUP_DISCOUNT_PCT": 0.10,
    "HOLD_MINUTES": 15,
    "MAX_PER_ORDER": 40,
    "ADVANCE_CUTOFF_DAYS": 14,
}

GEOMETRY = {
    "TRANSITION_BUFFER_S": 180,
    "REST_S": 600,
}

WINDOWS = {
    "APPEAL_WINDOW_MINUTES": 45,
    "BID_ACCEPTANCE_HOURS": 72,
    "AT_LARGE_PCT": 0.90,
}

DEFAULTS = {
    "TIME_DEDUCTION_PER_SECOND": 0.5,
    "SAFETY_DEDUCTION_POINTS": 2.0,
    "BOUNDARY_DEDUCTION_POINTS": 0.25,
    "WARMUP_DURATION_SECONDS": 900,
}

# Logical clock default at server startup (PRD logical-clock section).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Standard dates reused across fixtures: start 2026-09-05 puts the default
# clock (2026-08-01) on the ADVANCE side of the 14-day cutoff
# (2026-08-22T00:00:00Z).
EVENT_DEFAULTS = {
    "name": "Regionals",
    "venue_name": "Arena",
    "start_date": "2026-09-05",
    "end_date": "2026-09-06",
    "age_reference_date": "2026-08-31",
}

DIVISION_DEFAULTS = {
    "name": "D1",
    "category": "CHEER",
    "level": 3,
    "min_age": 11,
    "max_age": 18,
    "min_athletes": 1,
    "max_athletes": 4,
    "routine_time_limit_seconds": 150,
    "warmup_mats": ["A", "B", "C"],
    "schedule_start_at": "2026-09-05T10:00:00Z",
}

ATHLETE_DOB = "2010-05-01"  # age 16 at the 2026-08-31 reference date
