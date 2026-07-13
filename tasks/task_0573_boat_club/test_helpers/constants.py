"""Domain thresholds — numeric constants from the Boat Club PRD calculations."""

# --- Monetary / calculation constants (PRD §2.6, §3.6, §3.8) ---
TAX_PCT = 0.085                    # dues invoice per-line tax rate

FUEL_MIN_PCT = 25                  # fuel floor
FUEL_RATE_CENTS_PER_PCT = 100      # fuel fee per percentage point

DEDUCTIBLE_BY_TIER = {             # damage-fee tier deductible ceilings
    "CRUISE": 50000,
    "SAIL": 30000,
    "UNLIMITED": 10000,
}
SEVERE_SURCHARGE_CENTS = 20000     # added to ceiling only when severity == SEVERE

LATE_GRACE_MIN = 15                # late-return grace; strict '>' is billable
LATE_BLOCK_MIN = 30               # late-return billing block size
LATE_BLOCK_CENTS = 2500            # cents per started 30-minute block

NO_SHOW_SUSPEND_THRESHOLD = 3      # strikes at which a member is suspended
NO_SHOW_GRACE_MIN = 30             # grace after start_time before no-show
NO_SHOW_FEE_CENTS = 5000           # flat no-show fee

CLEANING_FEE_CENTS = 4000          # flat cleaning fee when SOILED
FEE_BLOCK_LIMIT_CENTS = 50000      # reservation fiscal block limit
MEMBER_TURNAROUND_MIN = 60         # required gap between a member's reservations

# --- Logical clock (PRD §2.5) ---
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# --- Default tier configurations used across setups ---
TIER_DEFAULTS = {
    "CRUISE": {
        "monthly_dues_cents": 15000,
        "max_active_reservations": 1,
        "reservations_per_week": 2,
        "reciprocal_access_allowed": False,
        "advance_booking_days_max": 7,
    },
    "SAIL": {
        "monthly_dues_cents": 25000,
        "max_active_reservations": 2,
        "reservations_per_week": 4,
        "reciprocal_access_allowed": True,
        "advance_booking_days_max": 14,
    },
    "UNLIMITED": {
        "monthly_dues_cents": 40000,
        "max_active_reservations": 3,
        "reservations_per_week": 7,
        "reciprocal_access_allowed": True,
        "advance_booking_days_max": 30,
    },
}
