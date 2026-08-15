"""Domain thresholds and pinned values from the PRD's calculation rules."""

# Fee constants (PRD §3.3, §3.6) — integer cents.
BASE_ANNUAL_FEE_CENTS = 12000
ADDITIONAL_DOG_FEE_CENTS = 3000
EARLY_BIRD_DISCOUNT_PCT = 0.10
REINSTATEMENT_FEE_CENTS = 2500
DAYS_IN_YEAR = 365

GUEST_WEEKDAY_FEE_CENTS = 1500
GUEST_WEEKEND_FEE_CENTS = 2250  # round_half_up(1500 * 1.5)

# Strike scoring (PRD §3.7) — integer points.
SEVERITY_POINTS = {"MINOR": 10, "MAJOR": 20, "SEVERE": 30}
PROVISIONAL_WEIGHT = 0.5
SUSPENSION_THRESHOLD = 30

# Waste stations (PRD §3.8) — integer percent.
FILL_PER_VISIT_PCT = 25
FILL_THRESHOLD_PCT = 80
FILL_CAP_PCT = 100

# Guest allotment (PRD §3.6) — passes per calendar month.
GUEST_MONTHLY_LIMIT = 2

# Logical clock (PRD §2.4) — startup default.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Term pinning (PRD §3.3) — memberships end on the final instant of the
# calendar year.
TERM_END_SUFFIX = "-12-31T23:59:59Z"

# Pinned expected values used across tests (derived from the PRD formulas):
# purchase on 2026-08-01 leaves 153 days through Dec 31 (inclusive);
# purchase on 2026-11-01 leaves 61 days.
DAYS_REMAINING_2026_08_01 = 153
DAYS_REMAINING_2026_11_01 = 61
FEE_2026_08_01_TWO_DOGS = 6288   # 5030 + 1258
FEE_2026_08_01_ONE_DOG = 5030
FEE_2026_11_01_TWO_DOGS = 2506   # 2005 + 501 (per-line rounding, then sum)
FEE_2026_11_01_ONE_DOG = 2005
FEE_EARLY_RENEWAL_TWO_DOGS = 13500   # 10800 + 2700
FEE_LAPSED_RENEWAL_TWO_DOGS = 17500  # 12000 + 3000 + 2500
FEE_LAPSED_RENEWAL_ONE_DOG = 14500   # 12000 + 0 + 2500
