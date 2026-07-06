"""Domain thresholds and constants derived from the PRD's calculation rules."""

# Waiting periods, in whole calendar years, by offense class (PRD Section 3.2).
WAITING_PERIOD_YEARS = {
    "INFRACTION": 1,
    "MISDEMEANOR": 2,
    "FELONY_CLASS_C": 3,
    "FELONY_CLASS_B": 5,
    "FELONY_CLASS_A": 7,
}
NEVER_ELIGIBLE = ["VIOLENT_FELONY"]

# Petition filing-fee constants (PRD Section 3.3 / 3.5).
BASE_FEE_CENTS = {
    "INFRACTION": 5000,
    "MISDEMEANOR": 12000,
    "FELONY_CLASS_C": 18000,
    "FELONY_CLASS_B": 25000,
    "FELONY_CLASS_A": 30000,
    "VIOLENT_FELONY": 30000,
}
DISP_MULT = {
    "CONVICTED": 1.0,
    "DISMISSED": 0.5,
    "ARREST_ONLY": 0.25,
    "ACQUITTED": 0.10,
}
EFILE_SURCHARGE = 0.075

# Fee-waiver determination constants (PRD Section 3.4).
FPL_BASE_CENTS = 1_500_000
FPL_PER_ADDL_CENTS = 530_000
FPL_MULTIPLIER = 1.25
ASSET_CAP_CENTS = 200_000

# Sealing-distribution retry cap (PRD Section 3.9).
MAX_ATTEMPTS = 2

# Logical clock (PRD Section 2.4). Boot default is 2026-05-01T00:00:00Z.
CLOCK_START = "2026-05-01T00:00:00Z"
# A clock value far past any day-scale objection window; used to guarantee that a
# served notification's window has elapsed (so it may be cleared) or that an
# objection is past its deadline, independent of the exact window length.
CLOCK_FAR_FUTURE = "2099-01-01T00:00:00Z"

# The per-record filing fee for a MISDEMEANOR / CONVICTED record, used pervasively
# in setup: 12000 * 1.0 * 1.075 = 12900 cents (round half up, whole cents).
STANDARD_MISDEMEANOR_FEE_CENTS = 12900
