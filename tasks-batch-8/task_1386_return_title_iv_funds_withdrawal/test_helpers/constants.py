"""Domain thresholds — numeric constants from PRD sections 2 and 3."""

THRESHOLDS = {
    # Minimum consecutive-day break-group span that is deductible (PRD 3.1).
    "MIN_DEDUCTIBLE_BREAK_DAYS": 5,
    # Earned-share cap: strictly above 0.600 earns 100% (PRD 3.4).
    "EARNED_CAP_THRESHOLD": 0.600,
    # Percentage precision: 3 decimal places, round half-up (PRD 2.7).
    "PCT_DECIMALS": 3,
    # Fifty-percent grant protection allowance (PRD 3.5).
    "GRANT_PROTECTION_RATE": 0.5,
    # Obligation due_date = determination_date + 45 calendar days (PRD 3.5/3.6).
    "RETURN_WINDOW_DAYS": 45,
    # Offer response_deadline = offered date + 14 calendar days (PRD 3.6).
    "OFFER_RESPONSE_DAYS": 14,
    # late_offer when offer created more than 30 days after determination (PRD 3.6).
    "OFFER_CREATION_DAYS": 30,
    # Logical clock startup value (PRD 2.5).
    "CLOCK_STARTUP_DEFAULT": "2026-08-01T00:00:00Z",
}

# Canonical calendar used across the suite. "T1": 2026-08-24..2026-12-11 is
# 110 calendar days; the 5-day break 2026-11-25..2026-11-29 is deductible,
# leaving total_days 105. Day 63 of the period is 2026-10-25 (63/105 = 0.600
# exactly); day 64 is 2026-10-26 (0.610); the midpoint day 53 of 105 is
# 2026-10-15 (0.505 rounded).
TERM_T1 = {
    "name": "Fall 2026",
    "start_date": "2026-08-24",
    "end_date": "2026-12-11",
    "break_start": "2026-11-25",
    "break_end": "2026-11-29",
    "calendar_days": 110,
    "deductible_break_days": 5,
    "total_days": 105,
    "day_63": "2026-10-25",
    "day_64": "2026-10-26",
    "day_62": "2026-10-24",
    "day_10": "2026-09-02",
    "midpoint_date": "2026-10-15",
}

# "T2": 2026-09-01..2026-12-09 is 100 calendar days, no breaks; midpoint
# day 50 is 2026-10-20 (0.500).
TERM_T2 = {
    "name": "Fall Mini",
    "start_date": "2026-09-01",
    "end_date": "2026-12-09",
    "calendar_days": 100,
    "total_days": 100,
    "midpoint_date": "2026-10-20",
}

# Non-overlapping 110-day terms for the TIERED vs PRO_RATA refund contrast.
TERM_TA = {
    "name": "Spring A",
    "start_date": "2027-01-11",
    "end_date": "2027-04-30",
    "refund_method": "TIERED",
    "day_11": "2027-01-21",
}
TERM_TB = {
    "name": "Summer B",
    "start_date": "2027-05-03",
    "end_date": "2027-08-20",
    "refund_method": "PRO_RATA",
    "day_11": "2027-05-13",
    # Day 67 of 110 -> 67/110 = 0.609 rounded; used to prove the earned cap
    # does not touch PRO_RATA refunds.
    "day_67": "2027-07-08",
}

TEST_DEFAULTS = {
    "INSTITUTIONAL_CHARGES_CENTS": 600_000,
    "PELL_AMOUNT_CENTS": 200_000,
    "LOAN_AMOUNT_CENTS": 300_000,
}
