"""Domain thresholds — numeric constants stated in the PRD.

PROBATION_WEIGHT (§2.6): a probationary journeyworker contributes one-half the
ratio capacity of a qualified one.
SUPERVISION_BUFFER_MINUTES (§3.4): on-the-job windows supervised by the same
journeyworker on the same date must be separated by at least fifteen minutes.

The standard wage ladder used across difficulty/corner setups (base wage
4000 cents) is captured here for reuse in fixtures:
  step 1: threshold 0  hrs, pct 0.50 -> 2000c
  step 2: threshold 8  hrs, pct 0.65 -> 2600c
  step 3: threshold 16 hrs, pct 0.80 -> 3200c
  step 4: threshold 24 hrs, pct 0.95 -> 3800c
"""

PROBATION_WEIGHT = 0.5
SUPERVISION_BUFFER_MINUTES = 15
EEO_TARGET_SUM = 100

# Standard program defaults.
BASE_WAGE_CENTS = 4000
DEFAULT_OJT_HOURS_REQUIRED = 16
DEFAULT_RTI_HOURS_REQUIRED = 8

# The reusable four-step wage ladder: (step_number, ojt_hours_threshold, wage_pct).
WAGE_LADDER_4 = [
    (1, 0, 0.50),
    (2, 8, 0.65),
    (3, 16, 0.80),
    (4, 24, 0.95),
]

# Wage in cents at each step of the standard ladder (base 4000c).
WAGE_AT_STEP = {1: 2000, 2: 2600, 3: 3200, 4: 3800}
