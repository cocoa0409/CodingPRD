"""Domain thresholds and default clock/fixture values from the PRD."""

# Logical clock default (PRD: before any clock call, the current time is
# exactly this instant).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Priority lead hours (PRD: forty-eight for STANDARD, twenty-four for
# URGENT, twelve for EMERGENT).
LEAD_HOURS = {"STANDARD": 48, "URGENT": 24, "EMERGENT": 12}

# Workflow thresholds (PRD sections on readiness, sterilization, access).
ESCALATION_WINDOW_MINUTES = 1440      # twenty-four hours before incision
PREP_BUFFER_MINUTES = 60              # case start minus one hour
DECON_MIN_MINUTES = 30                # decontamination minimum
MAX_REWORKS = 2                       # third QA failure quarantines
ACCESS_LEAD_MINUTES = 120             # window opens two hours before start
ACCESS_TRAIL_MINUTES = 30             # window ends thirty minutes after end
MINUTES_PER_HOUR = 60

# Standard fixture contract terms (vendor ACME).
DEFAULT_VENDOR = {
    "vendor_name": "Acme Surgical",
    "vendor_code": "ACME",
    "late_grace_minutes": 15,
    "late_rate_per_hour_cents": 5000,
    "late_penalty_cap_cents": 20000,
    "delay_surcharge_per_minute_cents": 250,
}

# Standard fixture case window (all times UTC).
DEFAULT_CASE_START = "2026-08-03T09:00:00Z"
DEFAULT_CASE_END = "2026-08-03T12:00:00Z"

# Derived standard deadline literals.
DEFAULT_REQUIRED_DELIVERY_BY_URGENT = "2026-08-02T09:00:00Z"   # start - 24h
DEFAULT_REQUIRED_STERILE_READY_BY = "2026-08-03T08:00:00Z"     # start - 60m
DEFAULT_WINDOW_START = "2026-08-03T07:00:00Z"                  # start - 120m
DEFAULT_WINDOW_END = "2026-08-03T12:30:00Z"                    # end + 30m

# Standard sterilizer profile (2 slots, 60-minute cycle, 30-minute cooldown).
DEFAULT_STERILIZER = {
    "unit_name": "ST-1",
    "slot_capacity": 2,
    "cycle_minutes": 60,
    "cooldown_minutes": 30,
}

# Standard rep credential expiry (well past the standard case end).
DEFAULT_CREDENTIAL_EXPIRES = "2026-08-10T00:00:00Z"
