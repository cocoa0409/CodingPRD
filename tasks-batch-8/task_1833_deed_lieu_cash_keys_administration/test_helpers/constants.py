"""Domain thresholds and numeric constants from the PRD (§2.4, §3.3-§3.9)."""

# --- Logical clock landmarks used across the suite (PRD §2.4) ---
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"          # startup default before any set call
BOARDING_CLOCK_ISO = "2026-05-01T00:00:00Z"         # loans/cases are boarded here
MARKETING_READY_CLOCK_ISO = "2026-08-01T00:00:00Z"  # 92 whole days after a 2026-05-01 list_date
STANDARD_LIST_DATE = "2026-05-01"
STANDARD_VACATE_DATE = "2026-09-01"

# --- Temporal thresholds ---
MARKETING_MIN_DAYS = 90                 # §3.3 certify-marketing minimum creditable days
MIN_VACATE_NOTICE_DAYS = 10             # §3.5 vacate_date >= now + 10 days
INSPECTION_MIN_NOTICE_HOURS = 24        # §3.6 scheduled_start >= now + 24 hours
INSPECTION_TRAVEL_BUFFER_MINUTES = 30   # §3.6 end-extended calendar buffer
HOLDOVER_GRACE_DAYS = 3                 # §3.9 grace window after vacate_date
HOLDOVER_DAILY_PENALTY_CENTS = 15000    # §3.6 per late day beyond grace
RECORDING_DEADLINE_DAYS = 30            # §3.8 confirm within handover_date + 30 days
MAX_NEGOTIATION_ROUNDS = 3              # §3.5 reoffer cap

# --- Provisional assistance quote (§3.5) ---
TIER_1_MAX_CENTS = 10000000
TIER_1_BASE_CENTS = 300000
TIER_2_MAX_CENTS = 25000000
TIER_2_BASE_CENTS = 500000
TIER_3_MAX_CENTS = 50000000
TIER_3_BASE_CENTS = 750000
TIER_4_BASE_CENTS = 1150000
ASSISTANCE_FLOOR_CENTS = 150000
ASSISTANCE_CAP_CENTS = 1200000
OCCUPANCY_MULTIPLIER = {"OWNER_OCCUPIED": 1.0, "TENANT_OCCUPIED": 0.8, "SECOND_HOME": 0.5}
HARDSHIP_BONUS_CENTS = {"INVOLUNTARY_UNEMPLOYMENT": 100000, "MEDICAL": 50000, "DIVORCE": 25000, "NONE": 0}
PENALTY_CAP_PCT = 0.5

# --- Condition deduction schedule (§3.6) ---
ITEM_BASE_CENTS = {
    "CLEANLINESS_FAIL": 14999,
    "DEBRIS_REMOVAL": 24999,
    "APPLIANCE_REMOVED": 39999,
    "FIXTURE_DAMAGE": 59999,
    "STRUCTURAL_DAMAGE": 149999,
}
SEVERITY_MULTIPLIER = {"STANDARD": 1.0, "MATERIAL": 1.5}

# --- Standard test economics (UPB 20000000 tier2 x1.0 + MEDICAL 50000) ---
STANDARD_LOAN = {
    "unpaid_principal_balance_cents": 20000000,
    "accrued_interest_cents": 300000,
    "escrow_advances_cents": 120000,
    "foreclosure_fees_cents": 80000,
    "note_annual_rate": 0.06,
    "fair_market_value_cents": 18000000,
    "delinquency_days": 90,
}
STANDARD_PER_DIEM_CENTS = 3288                 # round_half_up(20000000 * 0.06 / 365)
STANDARD_PROVISIONAL_CENTS = 550000            # 500000 * 1.0 + 50000
STANDARD_ACCRUAL_BASE_CENTS = 20500000         # UPB + accrued + escrow + fees
STANDARD_LIST_PRICE_CENTS = 19000000
