"""Domain thresholds and numeric constants from PRD §3.

Quoted PRD prose anchors each constant below.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Time / day thresholds (PRD §3.2, §3.3, §3.5, §3.6, §3.10)
# ---------------------------------------------------------------------------
THRESHOLDS = {
    # PRD §3.3: "If the recomputed value reaches at least 270, the loan
    # immediately progresses to default per §3.6"
    "DEFAULT_THRESHOLD_DAYS": 270,
    # PRD §3.2: "When the simulation clock crosses the boundary of 180
    # days past status_entered_at for a loan in GRACE..."
    "GRACE_DAYS": 180,
    # PRD §3.3 / §3.7: 365-day window for AGI recertification + interest math
    "DAYS_PER_YEAR": 365,
    # PRD §3.5: "the borrower's lifetime cumulative general-forbearance
    # days plus the number of days in the requested window must be at
    # most 1095"
    "FORBEARANCE_CAP_DAYS": 1095,
    # PRD §3.6: "When the clock-advance sees nine such REHAB_PAYMENT_RECORDED
    # actions within the prior 10 consecutive months"
    "REHAB_REQUIRED_PAYMENTS": 9,
    # PRD §3.10: "REHAB_PAYMENT_RECORDED actions whose occurred_at is at
    # or after now minus 304 days"
    "REHAB_WINDOW_DAYS": 304,
    # PRD §3.8: "The threshold for PSLF discharge is 120 qualifying
    # payments per loan."
    "PSLF_QUALIFYING_THRESHOLD": 120,
    # PRD §3.7: "the schedule is a level-payment fully amortizing
    # schedule over 120 months"
    "STANDARD_AMORTIZATION_MONTHS": 120,
    # PRD §3.7 / IDR floor: "for IBR and PAYE, if the rounded value is 0
    # and the pool is positive, the monthly payment is raised to 500
    # cents (a $5 minimum)"
    "IDR_MIN_PAYMENT_CENTS": 500,
    # PRD §2.4: "version that starts at 1 on creation and increments by
    # 1 on every successful mutation"
    "INITIAL_VERSION": 1,
}


# ---------------------------------------------------------------------------
# IDR multipliers and fractions (PRD §3.7)
# ---------------------------------------------------------------------------
# PRD §3.7: "The poverty multiplier depends on plan type — 1.50 for
# IBR, 1.50 for PAYE, 2.25 for SAVE."
IDR_MULTIPLIER = {
    "IBR": 1.50,
    "PAYE": 1.50,
    "SAVE": 2.25,
}

# PRD §3.7: "the plan-type income fraction — 0.15 for IBR, 0.10 for
# PAYE, 0.05 for SAVE."
IDR_FRACTION = {
    "IBR": 0.15,
    "PAYE": 0.10,
    "SAVE": 0.05,
}


# ---------------------------------------------------------------------------
# 2024 Federal Poverty Guidelines in cents (PRD §3.7)
# ---------------------------------------------------------------------------
# PRD §3.7:
# "The 48-state-plus-DC table reads $15,060 (1,506,000 cents) for family
#  size 1, $20,340 for size 2, $25,620 for size 3, $30,900 for size 4,
#  and $36,180 for size 5. The Alaska table reads $18,820 (1,882,000
#  cents) for size 1, $25,420 for size 2, $32,020 for size 3, $38,620
#  for size 4, and $45,220 for size 5. The Hawaii table reads $17,320
#  (1,732,000 cents) for size 1, $23,400 for size 2, $29,480 for size 3,
#  $35,560 for size 4, and $41,640 for size 5."
POVERTY_GUIDELINES_CENTS = {
    "48_DC": {
        1: 1_506_000,
        2: 2_034_000,
        3: 2_562_000,
        4: 3_090_000,
        5: 3_618_000,
    },
    "AK": {
        1: 1_882_000,
        2: 2_542_000,
        3: 3_202_000,
        4: 3_862_000,
        5: 4_522_000,
    },
    "HI": {
        1: 1_732_000,
        2: 2_340_000,
        3: 2_948_000,
        4: 3_556_000,
        5: 4_164_000,
    },
}

# Map state_code -> region key. Two-letter code; Alaska/Hawaii split,
# everything else uses the 48_DC table.
ALASKA_CODES = {"AK"}
HAWAII_CODES = {"HI"}


def poverty_line_cents(state_code: str, family_size: int) -> int:
    """Return PRD §3.7 poverty-line cents for (state, family_size).

    Family size is clamped to 1..5 since the PRD table only enumerates
    those rows; tests should always use family_size in [1,5].
    """
    if state_code in ALASKA_CODES:
        region = "AK"
    elif state_code in HAWAII_CODES:
        region = "HI"
    else:
        region = "48_DC"
    fs = max(1, min(5, int(family_size)))
    return POVERTY_GUIDELINES_CENTS[region][fs]


# ---------------------------------------------------------------------------
# Helper: round half up to integer (PRD §2.5 rounding rule)
# ---------------------------------------------------------------------------
def round_half_up_to_int(value: float) -> int:
    """Round half-up to nearest integer.

    PRD §2.5: "Whenever a calculation produces a non-integer cent
    result ... the result is rounded half-up to the nearest integer
    cent before it is written to a field."
    """
    # Python's banker's rounding would clobber .5 → even; we need
    # half-up everywhere per PRD.
    if value >= 0:
        return int(value + 0.5)
    return -int(-value + 0.5)


# ---------------------------------------------------------------------------
# Test defaults used by factories and fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "DEFAULT_PRINCIPAL_CENTS": 1_000_000,        # $10,000
    "DEFAULT_INTEREST_RATE_BPS": 500,            # 5.00% annual
    "DEFAULT_DISBURSEMENT_DATE": "2024-01-01T00:00:00.000Z",
    "DEFAULT_FAMILY_SIZE": 1,
    "DEFAULT_STATE_CODE": "CA",
    "DEFAULT_AGI_CENTS": 4_000_000,              # $40,000 annual
    "INITIAL_CLOCK": "2025-01-01T00:00:00.000Z",
}


__all__ = [
    "THRESHOLDS",
    "IDR_MULTIPLIER",
    "IDR_FRACTION",
    "POVERTY_GUIDELINES_CENTS",
    "ALASKA_CODES",
    "HAWAII_CODES",
    "poverty_line_cents",
    "round_half_up_to_int",
    "TEST_DEFAULTS",
]
