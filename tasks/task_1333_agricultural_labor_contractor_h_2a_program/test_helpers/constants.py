"""Domain thresholds and shared scenario literals (PRD 2.4, 2.6, 3.1-3.9)."""

# --- Logical clock (PRD 2.4) ---
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# --- Wage / guarantee constants (PRD 3.2, 3.7) ---
FEDERAL_MINIMUM_WAGE_CENTS = 725
CERT_LEAD_DAYS = 30
MAX_RFE_COUNT = 2
MAX_DAILY_CONSULAR_SLOTS = 6
DAYS_PER_DEBARMENT_YEAR = 365

# --- Civil money penalty constants (PRD 3.9) ---
BASE_WAGE_UNDERPAYMENT_CENTS = 150000
BASE_HOUSING_SUBSTANDARD_CENTS = 120000
BASE_TRANSPORT_VIOLATION_CENTS = 90000
BASE_RECRUITMENT_VIOLATION_CENTS = 110000
BASE_RECORDKEEPING_CENTS = 60000
WILLFUL_MULTIPLIER = 2
PER_KIND_CAP_CENTS = 1000000
GOOD_FAITH_DISCOUNT_PCT = 10

# --- Shared scenario literals used across tests ---
WD1 = {
    "state_code": "CA",
    "crop": "LETTUCE",
    "activity": "HARVEST",
    "effective_year": 2026,
    "aewr_hourly_cents": 1850,
    "prevailing_hourly_cents": 1775,
    "prevailing_piece_rate_cents_per_unit": 450,
    "piece_unit_name": "BOX",
}

WD_HOURLY_ONLY = {
    "state_code": "CA",
    "crop": "CHILE",
    "activity": "HARVEST",
    "effective_year": 2026,
    "aewr_hourly_cents": 700,
    "prevailing_hourly_cents": 710,
}

# J1: 2026-09-01..2026-10-20 -> 50 calendar days, 43 workdays,
# cutoff = transport threshold = 2026-09-25, certify deadline 2026-08-02.
J1 = {
    "title": "Fall lettuce",
    "crop": "LETTUCE",
    "activity": "HARVEST",
    "worksite_state": "CA",
    "work_start_date": "2026-09-01",
    "work_end_date": "2026-10-20",
    "daily_standard_hours": 8,
    "workers_requested": 4,
    "offered_hourly_cents": 1800,
    "offered_piece_rate_cents_per_unit": 400,
    "inbound_transport_cents": 60000,
    "outbound_transport_cents": 75000,
}
J1_START = "2026-09-01"
J1_END = "2026-10-20"
J1_CUTOFF_DATE = "2026-09-25"
J1_CERTIFY_DEADLINE = "2026-08-02"
J1_REQUIRED_FLOOR_CENTS = 1850
J1_EFFECTIVE_PIECE_RATE = 450

# J2: 2026-09-15..2026-11-03, workers_requested 2.
J2 = {
    "title": "J2 late lettuce",
    "crop": "LETTUCE",
    "activity": "HARVEST",
    "worksite_state": "CA",
    "work_start_date": "2026-09-15",
    "work_end_date": "2026-11-03",
    "daily_standard_hours": 8,
    "workers_requested": 2,
    "offered_hourly_cents": 1800,
    "offered_piece_rate_cents_per_unit": 400,
    "inbound_transport_cents": 60000,
    "outbound_transport_cents": 75000,
}
J2_START = "2026-09-15"

# J3: 2026-09-01..2026-09-20, workers_requested 8.
J3 = {
    "title": "J3 short harvest",
    "crop": "LETTUCE",
    "activity": "HARVEST",
    "worksite_state": "CA",
    "work_start_date": "2026-09-01",
    "work_end_date": "2026-09-20",
    "daily_standard_hours": 8,
    "workers_requested": 8,
    "offered_hourly_cents": 1800,
    "offered_piece_rate_cents_per_unit": 400,
    "inbound_transport_cents": 60000,
    "outbound_transport_cents": 75000,
}

# J4: hourly-only chile order, 2026-09-01..2026-09-20, floor 725.
J4 = {
    "title": "Chile harvest",
    "crop": "CHILE",
    "activity": "HARVEST",
    "worksite_state": "CA",
    "work_start_date": "2026-09-01",
    "work_end_date": "2026-09-20",
    "daily_standard_hours": 8,
    "workers_requested": 1,
    "offered_hourly_cents": 725,
    "inbound_transport_cents": 0,
    "outbound_transport_cents": 0,
}

CONSULATE = "MEX-MTY"

# Workdays (Sunday excluded) inside the J1 window used for work-log series.
J1_WORKDAYS_0901_TO_0911 = [
    "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05",
    "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
]
J1_WORKDAYS_0901_TO_0914 = J1_WORKDAYS_0901_TO_0911 + ["2026-09-12", "2026-09-14"]
