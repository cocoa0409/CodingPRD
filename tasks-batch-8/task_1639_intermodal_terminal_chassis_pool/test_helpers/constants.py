"""Domain constants — terminal defaults, rates, thresholds, standard timeline.

All values mirror PRD-stated rules: integer-cent money (§2.10), the 3600-second
congested booking cap (§2.8), the sixty-minute out-gate retirement horizon at
the operations checkpoint (§3.8), and the startup clock instant (§2.4).
"""

# Default terminal operating parameters used across tests.
TERMINAL_DEFAULTS = {
    "terminal_code": "BNSF-LA",
    "rail_cutoff_minutes_before_departure": 60,
    "gate_free_hours": 48,
    "per_diem_rate_cents": 15000,
    "storage_rate_cents": 8000,
    "flip_fee_cents": 5000,
    "max_stack_height": 3,
    "yard_slot_count": 20,
}

# PRD §2.4: the logical clock's startup default.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Standard timeline anchors used by composite fixtures.
T_GROUND = "2026-08-01T00:00:00Z"
T_WINDOW_START = "2026-08-02T09:00:00Z"
T_WINDOW_END = "2026-08-02T12:00:00Z"
T_CHECKIN = "2026-08-02T10:00:00Z"
T_TRAIN_DEPARTURE = "2026-08-10T12:00:00Z"

# PRD §2.8: booking-window cap while posture is CONGESTED.
CONGESTED_MAX_WINDOW_SECONDS = 3600

# PRD §3.8: an out-gated container retires to DEPARTED once its completing
# transaction's processed_at is at least sixty minutes in the past.
OUT_GATE_DEPARTURE_MINUTES = 60

# Standard per-test identifiers.
DEFAULTS = {
    "SLOT_CODE": "A-01-1",
    "SLOT_ROW": "A",
    "TIER_MAX": 3,
    "TRAIN_SYMBOL": "Z-ALTCHI",
    "CONTAINER_NUMBER": "BMOU1234567",
    "ISO_TYPE": "40FT",
    "POOL_CODE": "UP-POOL-A",
    "CHASSIS_NUMBER": "CH-001",
    "SCAC_CODE": "CARA",
    "CARRIER_NAME": "Carrier A",
    "CREDIT_LIMIT_CENTS": 1000000,
    "DRIVER_ID": "DRV-A",
    "GATE_LANE": "L1",
}
