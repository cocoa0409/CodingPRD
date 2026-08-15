"""Domain thresholds and constants — numeric rules from the PRD."""

# PRD §2.4: logical clock initial value before any set call.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD §2.8: standing thresholds, inclusive at the bottom of each band.
PROBATION_AT_POINTS = 10
SUSPENDED_AT_POINTS = 20

# PRD §3.4: weekend-leave allowance tiers and cap.
ALLOWANCE_BASE_BY_GRADE = {9: 4, 10: 4, 11: 6, 12: 8}
ALLOWANCE_CAP = 10

# PRD §3.8: storage pricing and break-housing fee constants.
STORAGE_RATE_CENTS_PER_CUFT_WEEK = 250
EARLY_BIRD_DISCOUNT = 0.15
EARLY_BIRD_DAYS_BEFORE_BREAK = 30
ROOM_CHARGE_FLAT_CENTS = 20000
DEPOSIT_CAP_CENTS = 5000
DEPOSIT_RATE = 0.10

# PRD §3.7: appeal window anchored at decided_at.
APPEAL_WINDOW_HOURS = 168

# PRD §3.4: sign-out grace window around departs_at.
SIGN_OUT_EARLY_HOURS = 2
SIGN_OUT_LATE_HOURS = 6

# PRD §3.3: roommate compatibility weights.
COMPAT_WEIGHTS = {
    "sleep_schedule": 12,
    "cleanliness": 8,
    "noise_tolerance": 8,
    "guests_comfort": 4,
}

# A well-formed UUID that is guaranteed absent from a fresh database.
NONEXISTENT_UUID = "11111111-2222-3333-4444-555555555555"
