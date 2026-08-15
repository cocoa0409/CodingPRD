"""Domain thresholds and constants from PRD calculation rules (§2.4–§2.9, §3)."""

# Logical clock startup default (PRD §2.4): before any clock-setting call the
# logical clock reads exactly this instant.
STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD §3.3: is_retroactive is true exactly when days_since_posting > 90.
    "RETROACTIVE_DAYS": 90,
    # PRD §3.4: |variance_pp| > 5.00 requires a payroll_adjustment_note.
    "VARIANCE_TOLERANCE_PP": 5.00,
    # PRD §3.4: key-personnel reduction floor at certification.
    "KEY_PERSONNEL_FLOOR": 0.75,
    # PRD §3.5: per-subaward federal MTDC cap, in cents (25,000 USD).
    "SUBAWARD_MTDC_CAP": 2_500_000,
    # PRD §3.6: late interest accrues only after a 60-day grace.
    "INTEREST_GRACE_DAYS": 60,
    # PRD §3.6: aging bucket boundaries.
    "AGING_CURRENT_MAX_DAYS": 30,
    "AGING_D31_60_MAX_DAYS": 60,
    "AGING_D61_90_MAX_DAYS": 90,
    "AGING_D91_120_MAX_DAYS": 120,
    # PRD §2.9: FFR falls due 120 days after current_end_date; 30-day grace.
    "FFR_DUE_DAYS": 120,
    "FINAL_REPORT_GRACE_DAYS": 30,
    # PRD §3.8: rebudget significance ratio (exactly 25% is NOT significant).
    "REBUDGET_SIGNIFICANCE_PCT": 25,
}

# Common salary figures used across the design-driven fixtures.
TEST_DEFAULTS = {
    "PI_IBS_ANNUAL_CENTS": 12_000_000,          # 120,000 USD, 12-month appointment
    "HIGH_IBS_ANNUAL_CENTS": 24_000_000,        # above the 200,000 USD cap
    "NINE_MO_IBS_ANNUAL_CENTS": 13_500_000,     # 9-month appointment -> 1,500,000/mo
    "SPONSOR_SALARY_CAP_CENTS": 20_000_000,     # 200,000 USD 12-month-equivalent cap
    "F_AND_A_RATE_BPS": 5000,                   # 50.00%
    "FRINGE_RATE_BPS": 3000,                    # 30.00% provisional
    "LATE_PAYMENT_APR_BPS": 1000,               # 10.00% APR
}

# Distinct operator ids for segregation-of-duties scenarios (PRD §3.3: the
# approving accountant's X-User-ID must differ from submitted_by_user_id).
OPERATOR_IDS = {
    "COORDINATOR_1": "gc-1",
    "ACCOUNTANT_1": "ga-1",
    "ACCOUNTANT_2": "ga-2",
    "ACCOUNTANT_9": "ga-9",
    "OFFICER_1": "spo-1",
    "SPONSOR_1": "sponsor-1",
    "ADMIN_1": "sysadmin-1",
}
