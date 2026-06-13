"""Domain thresholds — numeric constants from the PRD's business rules."""

# No-show standing thresholds (PRD §2.9) — inclusive (>=).
NO_SHOW_THRESHOLDS = {
    "WATCH_THRESHOLD": 2,    # strikes >= 2 (and < 4) -> WATCH
    "BLOCKED_THRESHOLD": 4,  # strikes >= 4 -> BLOCKED
}

# Server-side defaults (PRD §3.1 / §3.3).
DEFAULTS = {
    "HOLD_WINDOW_MINUTES": 120,    # Store.hold_window_minutes default
    "CUTOFF_OFFSET_MINUTES": 30,   # PickupSlot.cutoff_offset_minutes default
}

# Pagination defaults (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}
