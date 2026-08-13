"""Domain thresholds and rate constants named in the PRD.

Sources:
- PRD section 3.8: classification base rates, shift multipliers, fringe,
  daily/weekly overtime thresholds.
- PRD section 3.6: alignment tolerance classes.
- PRD section 3.2: seven-day foundation cure.
- PRD section 3.3: thirty-minute lockout clearance buffer.
- PRD section 2.5: logical-clock startup default.
"""

# PRD 3.8 prevailing-wage base hourly rates, integer cents per hour.
CLASS_RATE_CENTS = {
    "MW_JOURNEYMAN": 8500,
    "MW_APPRENTICE": 5600,
    "MW_FOREMAN": 9800,
    "OPERATOR": 7200,
}

OT_MULT = 1.5                 # overtime multiplier (PRD 3.8)
NIGHT_SHIFT_MULT = 1.10       # NIGHT shift multiplier (PRD 3.8)
DAY_SHIFT_MULT = 1.0          # DAY shift multiplier (PRD 3.8)
FRINGE_CENTS_PER_HOUR = 2100  # fringe applied to every hour worked (PRD 3.8)
DAILY_OT_THRESHOLD_H = 8      # daily straight-time ceiling (PRD 3.8)
WEEKLY_OT_THRESHOLD_H = 40    # weekly straight-time ceiling (PRD 3.8)

# PRD 3.6 alignment tolerance classes (raw units; equality passes).
OFFSET_TOLERANCE_MILS = {"STANDARD": 5.0, "PRECISION": 2.0}
ANGULAR_TOLERANCE_MILS_PER_IN = {"STANDARD": 1.0, "PRECISION": 0.5}

# PRD 3.2 foundation cure window.
MIN_CURE_DAYS = 7

# PRD 3.3 lockout clearance buffer, minutes.
LOCKOUT_BUFFER_MIN = 30

# PRD 3.1 retainage default and range.
DEFAULT_RETAINAGE_PCT = 0.10
MAX_RETAINAGE_PCT = 0.20

# PRD 2.5 logical clock startup default.
CLOCK_START_DEFAULT = "2026-08-01T00:00:00Z"

# Common test clock positions.
CLOCK_CURED = "2026-08-08T00:00:00Z"      # exactly 7 days after a 2026-08-01 pour
CLOCK_NOT_CURED = "2026-08-06T00:00:00Z"  # 5 days after a 2026-08-01 pour
CLOCK_IN_LIFT_WINDOW = "2026-08-10T11:00:00Z"

# Default commercial terms for test projects.
DEFAULT_CONTRACT_AMOUNT_CENTS = 5_000_000
DEFAULT_EQUIPMENT_HOURLY_RATE_CENTS = 45_000

# Default lift booking window used across tests (2026-08-10, four hours).
DEFAULT_LIFT_START = "2026-08-10T10:00:00Z"
DEFAULT_LIFT_END = "2026-08-10T14:00:00Z"
DEFAULT_CRANE_REF = "CR-7"
