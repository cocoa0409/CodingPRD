"""Domain thresholds and numeric constants named in the PRD (§2.5, §3)."""

# Contrast ceiling (PRD §3.2): raw = CONTRAST_MULTIPLIER * weight_kg /
# serum_creatinine, capped at CONTRAST_CAP_ML, one decimal place half-up.
CONTRAST_MULTIPLIER = 5.0
CONTRAST_CAP_ML = 300.0

# Radiation alert latch threshold in mGy (PRD §3.6).
RADIATION_ALERT_MGY = 5000.0

# Room turnover buffer appended to each committed case window (PRD §3.3).
TURNOVER_BUFFER_MINUTES = 20

# Committed recovery window length (PRD §3.7).
RECOVERY_MINUTES = 90

# Registry submission window after actual_end (PRD §3.9).
SUBMISSION_WINDOW_DAYS = 30

# Base case durations by procedure type in whole minutes (PRD §3.2).
BASE_MINUTES = {
    "DIAGNOSTIC_CATHETERIZATION": 45,
    "PCI": 90,
    "STEMI_PCI": 75,
    "DEVICE_IMPLANT": 60,
    "EP_STUDY": 120,
}

# Setup allowance tiers (PRD §3.2): zero for STEMI; otherwise 0 / 15 / 30 by
# equipment count (0 / 1-2 / 3+).
SETUP_MINUTES_NONE = 0
SETUP_MINUTES_ONE_OR_TWO = 15
SETUP_MINUTES_THREE_PLUS = 30

# Logical clock startup default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Standard scenario timestamps used across fixtures.
T_0800 = "2026-08-10T08:00:00Z"
T_0900 = "2026-08-10T09:00:00Z"
T_1000 = "2026-08-10T10:00:00Z"
T_1030 = "2026-08-10T10:30:00Z"
T_1130 = "2026-08-10T11:30:00Z"

FAR_FUTURE_EXPIRY = "2027-01-01T00:00:00Z"
