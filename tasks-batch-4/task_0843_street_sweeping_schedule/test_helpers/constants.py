"""Domain thresholds — numeric constants from the PRD's calculations (§2.7, §3.5, §3.7)."""

# Citation fine (PRD §3.7)
BASE_FINE_CENTS = 6000
LATE_FEE_TIER_1_CENTS = 1500       # 1..15 whole days late
LATE_FEE_TIER_2_CENTS = 3000       # 16..30 whole days late
LATE_FEE_TIER_3_CENTS = 5000       # > 30 whole days late
FINE_CAP_CENTS = 20000

# Debris tonnage (PRD §2.7)
LBS_PER_TON = 2000

# Makeup scheduling (PRD §3.5)
MAKEUP_OFFSET_DAYS = 7

# Shift overlap buffer (PRD §3.3)
SHIFT_BUFFER_MINUTES = 30

# Logical clock default at server startup (PRD §2.5)
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

THRESHOLDS = {
    "BASE_FINE_CENTS": BASE_FINE_CENTS,
    "LATE_FEE_TIER_1_CENTS": LATE_FEE_TIER_1_CENTS,
    "LATE_FEE_TIER_2_CENTS": LATE_FEE_TIER_2_CENTS,
    "LATE_FEE_TIER_3_CENTS": LATE_FEE_TIER_3_CENTS,
    "FINE_CAP_CENTS": FINE_CAP_CENTS,
    "LBS_PER_TON": LBS_PER_TON,
    "MAKEUP_OFFSET_DAYS": MAKEUP_OFFSET_DAYS,
    "SHIFT_BUFFER_MINUTES": SHIFT_BUFFER_MINUTES,
}
