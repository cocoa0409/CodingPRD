"""Domain thresholds — numeric constants from PRD §3.4 and §3.9 calculations."""

# ─── PRD §3.4: net-monthly-income calculation ──────────────────────────

EARNED_INCOME_DEDUCTION_PCT = 0.20  # 20% earned-income deduction

# Standard deduction per household size (cents). PRD §3.4: 19,800 for sizes 1-3;
# 21,300 for size 4; 24,900 for size 5; 28,500 for size 6+.
STANDARD_DEDUCTION_BY_SIZE = {
    1: 19_800,
    2: 19_800,
    3: 19_800,
    4: 21_300,
    5: 24_900,
    6: 28_500,
}

# Standard Utility Allowance — admitted only when heap_recipient == true.
STANDARD_UTILITY_ALLOWANCE_CENTS = 6_700  # $67.00

# Net-income ceilings (PRD §3.4) — used by LIMIT_CHECK variant.
NET_INCOME_LIMIT_BY_SIZE = {
    1: 117_500,
    2: 158_900,
    3: 200_300,
    4: 241_700,
    5: 283_100,
    6: 324_500,
}
NET_INCOME_LIMIT_EACH_ADDL = 41_400


# ─── PRD §3.4: monthly-allotment calculation ───────────────────────────

BENEFIT_REDUCTION_PCT = 0.30  # 30% of net income

# Maximum allotment per household size (cents). PRD §3.4: 29,100 for size 1;
# 53,500 for size 2; 76,600 for size 3; 97,300 for size 4; 115,500 for size 5;
# 138,600 for size 6.
MAX_ALLOTMENT_BY_SIZE = {
    1: 29_100,
    2: 53_500,
    3: 76_600,
    4: 97_300,
    5: 115_500,
    6: 138_600,
}
EXTRA_PER_PERSON_OVER_6 = 21_100

# Floor for size 1 or 2 households.
MIN_ALLOTMENT_SIZE_1_2 = 2_300  # $23.00

# Default federally mandated emergency supplement floor.
DEFAULT_MIN_SUPPLEMENT_CENTS = 9_500  # $95.00


# ─── PRD §3.9: fraud-velocity score ────────────────────────────────────

VELOCITY_THRESHOLD_CENTS = 80_000  # $800
VELOCITY_COUNT_PENALTY_CENTS = 5_000  # $50 per transaction
MIN_TX_FOR_FLAG = 4


# ─── PRD §3.3: ABAWD waiver eligibility ────────────────────────────────

ABAWD_COUNTY_UNEMPLOYMENT_THRESHOLD = 10.00  # percent
ABAWD_MIN_WORK_HOURS = 80


# ─── PRD §3.6: card replacement abuse window ───────────────────────────

CARD_REPLACE_ABUSE_THRESHOLD = 3  # >= 3rd replacement triggers fraud flag
CARD_REPLACE_ABUSE_WINDOW_DAYS = 90  # rolling window


# ─── PRD §3.2: certification period ────────────────────────────────────

CERTIFICATION_PERIOD_MONTHS = 12


# ─── PRD §3.10 / §3.2: time-based system transitions ───────────────────

APPLICATION_EXPIRY_DAYS = 30
