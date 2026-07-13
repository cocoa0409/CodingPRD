"""Domain thresholds and defaults — numeric constants from the PRD."""

# Fee / fiscal thresholds (PRD §3.1, §3.4, §3.5, §3.6).
THRESHOLDS = {
    "GRACE_DAYS": 2,                 # late-fee grace period (PRD §3.6)
    "SUSPEND_THRESHOLD_CENTS": 2000, # auto-suspend / balance gate (PRD §3.1, §3.4)
    "LOST_THRESHOLD_DAYS": 30,       # overdue -> LOST (PRD §3.4)
    "DEP_RATE_PER_YEAR": 0.10,       # annual depreciation rate (PRD §3.5)
    "SALVAGE_FLOOR_PCT": 0.20,       # salvage floor percentage (PRD §3.5)
    "REPAIR_FLAT_CENTS": 1500,       # flat repair charge for MINOR_DAMAGE (PRD §3.5)
}

# Member/item registration defaults (PRD §3.1, §3.2).
DEFAULTS = {
    "MAX_ACTIVE_LOANS": 5,
    "MAX_ACTIVE_HOLDS": 3,
    "BALANCE_LIMIT_CENTS": 2000,
    "MAX_RENEWALS": 2,
}

# The server's logical clock defaults to this instant on startup (PRD §2.5).
SERVER_START_CLOCK = "2026-03-01T00:00:00Z"
