"""Domain thresholds and shared constants from the PRD."""

# PRD §2.8 — the logical clock starts here before any set call.
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# PRD §3.4 — grace window length after current_period_end.
GRACE_PERIOD_DAYS = 30

# PRD §3.9 — unfulfilled-pledge follow-up window before write-off.
WRITEOFF_WINDOW_DAYS = 60

# PRD §3.3 — mandatory buffer between breaks of one drive.
BREAK_BUFFER_MINUTES = 5

# Default drive window used across setups (inclusive start, exclusive end).
DRIVE_WINDOW = {
    "starts_at": "2026-08-01T00:00:00Z",
    "ends_at": "2026-08-15T00:00:00Z",
}

# Default break slot inside the drive window.
BREAK_SLOT = {
    "starts_at": "2026-08-02T18:00:00Z",
    "ends_at": "2026-08-02T18:20:00Z",
}

# Clock reading at which a membership paid on 2026-08-01 (period end
# 2027-08-01) has passed both the period end and the 30-day grace boundary.
LAPSED_CLOCK_ISO = "2027-10-15T00:00:00Z"

# Clock reading 61 days after a pledge captured at the 2026-08-01 default
# clock, i.e. past the 60-day write-off follow-up window.
WRITEOFF_READY_CLOCK_ISO = "2026-10-02T00:00:00Z"
