"""Domain thresholds and shared constants from the PRD."""

# Delinquency escalation thresholds (PRD section 3.6)
NOTICE_DAY_THRESHOLD = 10
DISCONNECT_DAY_THRESHOLD = 45

# Board voting quorum (PRD section 3.9)
QUORUM_FOR = 3
QUORUM_AGAINST = 3

# USDA reserve covenant (PRD section 3.8)
WITHDRAWAL_FLOOR_RATIO = 0.75
RATE_COVENANT_RATIO = 1.1
RESERVE_DEPOSIT_DIVISOR = 120  # annual debt service / 120 per monthly deposit

# Annexation fee split (PRD section 3.10)
FEASIBILITY_FEE_FLOOR_CENTS = 25000
FEASIBILITY_FEE_PCT = 0.2

# Boil order windows (PRD section 3.11)
NOTIFY_WINDOW_HOURS = 24
SAMPLING_WINDOW_HOURS = 72
REQUIRED_CLEAR_SAMPLES = 2

# Tiered pricing (PRD section 3.4)
GALLONS_PER_KGAL = 1000

# Logical clock default (PRD section 2.4)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Standard rate schedule used across scenarios (base 3500 covers 2000 gal,
# tier2 450/kgal up to 10000 cumulative, tier3 700/kgal beyond, reconnect 5000)
SCHEDULE_S1 = {
    "schedule_label": "S1",
    "base_minimum_cents": 3500,
    "included_gallons": 2000,
    "tier2_rate_cents_per_kgal": 450,
    "tier2_cap_gallons": 10000,
    "tier3_rate_cents_per_kgal": 700,
    "tap_fee_schedule": {
        "RESIDENTIAL": 75000,
        "COMMERCIAL": 150000,
        "AGRICULTURAL": 120000,
    },
    "reconnect_fee_cents": 5000,
}

# Standard cycle windows (half-open [start, end); due >= end)
CYCLE_1 = {
    "period_start_utc": "2026-08-01T00:00:00Z",
    "period_end_utc": "2026-09-01T00:00:00Z",
    "due_date_utc": "2026-09-10T00:00:00Z",
}
CYCLE_1_EARLY_DUE = {
    "period_start_utc": "2026-08-01T00:00:00Z",
    "period_end_utc": "2026-09-01T00:00:00Z",
    "due_date_utc": "2026-08-10T00:00:00Z",
}
CYCLE_2 = {
    "period_start_utc": "2026-09-01T00:00:00Z",
    "period_end_utc": "2026-10-01T00:00:00Z",
    "due_date_utc": "2026-10-10T00:00:00Z",
}
CYCLE_3 = {
    "period_start_utc": "2026-10-01T00:00:00Z",
    "period_end_utc": "2026-11-01T00:00:00Z",
    "due_date_utc": "2026-11-10T00:00:00Z",
}
CYCLE_4 = {
    "period_start_utc": "2026-11-01T00:00:00Z",
    "period_end_utc": "2026-12-01T00:00:00Z",
    "due_date_utc": "2026-12-10T00:00:00Z",
}

# Clock instants relative to CYCLE_1_EARLY_DUE (due 2026-08-10)
CLOCK_DUE_PLUS_10D = "2026-08-20T00:00:00Z"   # exactly 10 days past due
CLOCK_DUE_PLUS_45D = "2026-09-24T00:00:00Z"   # exactly 45 days past due

# Boil-order scenario clock
CLOCK_ORDER_ISSUED = "2026-08-05T12:00:00Z"
SAMPLE_IN_WINDOW = "2026-08-06T12:00:00Z"
SAMPLE_IN_WINDOW_2 = "2026-08-07T12:00:00Z"
SAMPLE_IN_WINDOW_3 = "2026-08-07T18:00:00Z"
SAMPLE_AT_WINDOW_EDGE = "2026-08-08T12:00:00Z"      # issued + 72h exactly
SAMPLE_PAST_WINDOW = "2026-08-08T12:00:01Z"         # issued + 72h + 1s
