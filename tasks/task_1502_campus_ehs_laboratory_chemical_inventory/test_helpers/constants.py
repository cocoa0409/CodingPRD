"""Domain thresholds and constants — numeric values stated in PRD §2.5, §2.7, §3.3-3.5."""

# PRD §2.5: logical clock startup default
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD §2.7: per-class permit thresholds in gallons
PERMIT_THRESHOLDS_GAL = {
    "FLAMMABLE": 10.0,
    "OXIDIZER": 10.0,
    "CORROSIVE": 5.0,
    "TOXIC": 1.0,
    "CONTROLLED_SUBSTANCE": 0.0,
    "SELECT_AGENT": 0.0,
}

# PRD §3.4: disposal estimate constants
PICKUP_BASE_FEE = 75.00
DISPOSAL_RATE_PER_GAL = {
    "FLAMMABLE": 12.50,
    "OXIDIZER": 11.00,
    "CORROSIVE": 9.75,
    "TOXIC": 21.20,
    "CONTROLLED_SUBSTANCE": 45.00,
    "SELECT_AGENT": 60.00,
}

# PRD §3.4: dock scheduling buffer
DOCK_BUFFER_MINUTES = 30

# PRD §3.3: accumulation overstay limit
ACCUMULATION_MAX_DAYS = 365

# PRD §3.5: corrective-action due-date offsets from completed_at
CA_DUE_DAYS = {"MAJOR": 14, "MINOR": 30}

# PRD §3.5: inspection scoring constants
MAJOR_DEDUCTION = 20
MINOR_DEDUCTION = 5
FLAT_DEDUCTION = 10
PASS_THRESHOLD = 70

# Test-driving convenience values
FUTURE_TRAINING_DUE = "2027-01-01T00:00:00Z"
DOCK_ID = "DOCK-1"
DOCK_WINDOW_START = "2026-08-10T10:00:00Z"
DOCK_WINDOW_END = "2026-08-10T11:00:00Z"
