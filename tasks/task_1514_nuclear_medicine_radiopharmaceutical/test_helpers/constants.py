"""Domain thresholds and canonical timestamps used across the test suite.

Numeric limits come from the PRD's calculation narratives (§2.5–§3.8).
All instants are on the server-side logical clock, which starts at
2026-08-01T00:00:00Z before any call has been made (PRD §2.4).
"""

THRESHOLDS = {
    # Hot-lab aggregate capacity: rejected only when strictly greater (PRD §3.2)
    "HOT_LAB_CAPACITY_MBQ": 37000,
    # Arrival window half-width around scheduled_arrival_at (PRD §3.2)
    "ARRIVAL_WINDOW_HALF_WIDTH_MIN": 30,
    # Receipt tolerance: |measured - decayed reference| <= 10% passes (PRD §3.2)
    "RECEIPT_TOLERANCE_RATIO": 0.10,
    # Administration window half-width around administration_scheduled_at (PRD §3.5)
    "ADMIN_WINDOW_MINUTES": 60,
    # Regulatory 1-meter dose-rate release limit (PRD §3.8)
    "RELEASE_DOSE_RATE_LIMIT_USV_H": 70,
    # Decay-in-storage: clearance allowed after ten half-lives (PRD §3.7)
    "HALF_LIVES_REQUIRED": 10,
    # Clearance activity ceiling, inclusive (PRD §3.7)
    "CLEARANCE_ACTIVITY_LIMIT_MBQ": 0.05,
    # Preparation overage tiers by isotope half-life (PRD §3.4)
    "PREP_OVERAGE_SHORT_HALFLIFE": 1.10,
    "PREP_OVERAGE_MID_HALFLIFE": 1.05,
    "PREP_OVERAGE_LONG_HALFLIFE": 1.00,
    "SHORT_HALFLIFE_BOUND_MIN": 120,
    "LONG_HALFLIFE_BOUND_MIN": 1440,
    # Activity figures are rounded half-up to three decimals (PRD §2.5)
    "ACTIVITY_DECIMALS": 3,
}

# Canonical isotope parameter sets (F-18: short half-life tier; I-131: long tier)
F18_PARAMS = {
    "name": "F-18 FDG",
    "half_life_minutes": 110,
    "spill_major_threshold_mbq": 37,
    "release_activity_limit_mbq": 1221,
    "min_usable_activity_mbq": 10,
}
I131_PARAMS = {
    "name": "I-131",
    "half_life_minutes": 11568,
    "spill_major_threshold_mbq": 37,
    "release_activity_limit_mbq": 1221,
    "min_usable_activity_mbq": 1,
}

# Canonical logical-clock instants used by the fixtures
T_CLOCK_START = "2026-08-01T08:00:00Z"
T_PREP = "2026-08-01T08:30:00Z"
T_ADMIN = "2026-08-01T10:20:00Z"          # exactly one F-18 half-life after T_PREP
T_ORDER_EXPIRY_F18 = "2026-08-01T14:00:00Z"  # T_ADMIN + 2 * 110 min (PRD §3.3)
T_APPT_START = "2026-08-01T10:00:00Z"
T_APPT_END = "2026-08-01T10:30:00Z"
T_I131_ADMIN = "2026-08-01T09:00:00Z"
T_LICENSE_EXPIRY = "2027-08-01T00:00:00Z"
T_AU_EXPIRY = "2027-01-01T00:00:00Z"

TEST_DEFAULTS = {
    "PATIENT_NAME": "P One",
    "PATIENT_WEIGHT_KG": 70,
    "ROOM_NAME": "Room-1",
    "ROOM_BUFFER_MINUTES": 15,
    "LICENSE_NUMBER": "L-100",
    "LICENSE_MAX_POSSESSION_MBQ": 100000,
    "CONDITION_MAX_POSSESSION_MBQ": 50000,
    "DELIVERY_REFERENCE_MBQ": 5000,
    "PRESCRIBED_ACTIVITY_MBQ": 100,
}
