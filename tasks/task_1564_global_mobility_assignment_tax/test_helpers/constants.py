"""Domain thresholds and money constants from the PRD calculation rules (§2.5, §3.3, §3.6)."""

# Hypothetical tax schedule (PRD §3.3)
TAX = {
    "EXEMPTION_PER_FAMILY_MEMBER_CENTS": 200000,
    "BRACKET1_TOP_CENTS": 5000000,
    "BRACKET2_TOP_CENTS": 10000000,
}

# Employer-side rates (PRD §3.3)
HOST_TAX_RATE_PCT = 40          # employer_host_tax fixed-point gross-up
SOCSEC_RATE_PCT_X10000 = 765    # 7.65% employer social security

# Program defaults (PRD §3.1)
PROGRAM_DEFAULTS = {
    "COST_OVERRUN_THRESHOLD_PCT": 110,
    "MAX_ASSIGNMENT_DURATION_DAYS": 1825,
    "PER_DIEM_ANNUAL_DAY_CAP": 365,
}

# Logical clock startup value (PRD §2.5)
CLOCK_START_DATE = "2026-08-01"

# Pagination defaults (PRD §2.3)
PAGINATION = {"DEFAULT_LIMIT": 10, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# Expected values for the canonical activated assignment used across tests:
# program US defaults; employee family_size 2, base 10_800_000;
# policy JP 7500/day, cola 15, housing cap 300000; split 60/40;
# record 2026-09: total 900000, per_diem 20 days, receipts 310000.
CANONICAL = {
    # Record math with CoC ISSUED (coc_exempt true -> socsec 0)
    "REC_HOME_GROSS": 540000,          # round_half_up(900000 * 60 / 100)
    "REC_HOST_GROSS": 360000,          # residual
    "REC_PER_DIEM": 172500,            # round_half_up(7500*115/100)=8625, * 20
    "REC_HOUSING": 300000,             # min(300000, 310000)
    "REC_HYPO_TAX": 135000,            # PROVISIONAL on 900000x12 less 400000 exemption
    "REC_EMPLOYER_HOST_TAX": 240000,   # fixed point: 0.40 * (360000+240000) = 240000
    "REC_SOCSEC_EXEMPT": 0,
    "REC_PERIOD_COST_EXEMPT": 1072500,  # 360000+240000+0+172500+300000
    # Same record without exemption
    "REC_SOCSEC_NONEXEMPT": 27540,     # round_half_up(360000 * 0.0765)
    # Settlement against filed gross 1_500_000 (family_size 2)
    "FINAL_HYPO_ON_1500000": 110000,   # 0.10 * (1500000 - 400000)
    # Cost projection monthly cost over the 12-month window 2026-09..2027-08
    "PROJ_MONTHS": 12,
    "PROJ_MONTHLY_EXEMPT": 1158750,     # 360000 + 240000 + 0 + 258750 + 300000
    "PROJ_MONTHLY_NONEXEMPT": 1186290,  # 360000 + 240000 + 27540 + 258750 + 300000
    "PROJ_PROVISIONAL_TOTAL_EXEMPT": 13905000,  # 12 * 1158750
}
