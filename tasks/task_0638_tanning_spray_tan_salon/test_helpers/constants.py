"""Domain thresholds — numeric constants from the PRD's calculations (§3.8).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# UV dose schedule (PRD §3.8 "UV dose allowance").
STEP_SECONDS = 30  # +30s per completed UV session

SKIN_BASE_SECONDS = {
    "II": 90,
    "III": 120,
    "IV": 180,
    "V": 240,
    "VI": 300,
}

SKIN_CAP_SECONDS = {
    "II": 240,
    "III": 480,
    "IV": 600,
    "V": 720,
    "VI": 900,
}

# Frequency / cool-down (PRD §3.5, §3.6).
MINOR_WEEKLY_UV_CAP = 1
COOLDOWN_SECONDS = 86400  # 24 hours between consecutive UV session start_at

# Equipment service threshold (PRD §3.8 "Service threshold").
SERVICE_THRESHOLD = 2

# Billing cycle (PRD §2.5, §3.2, §3.8).
CYCLE_DAYS = 30
GRACE_DAYS = 7

# Buffers (PRD §3.6).
DEFAULT_TURNAROUND_SECONDS = 600
DEFAULT_VENTILATION_BUFFER_SECONDS = 300

# A syntactically valid UUID that should never resolve to a real entity.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

# Convenient test defaults.
TEST_DEFAULTS = {
    "BASIC_FEE": 3000,
    "PREMIUM_FEE": 8000,
    "UNLIMITED_FEE": 6000,
}
