"""Domain thresholds and fixed test values from the PRD's pricing and timing rules."""

# --- Sweep pricing tiers (PRD §3.2 / §3.4) ---
SWEEP_BASE_CENTS = {1: 15000, 2: 24000, 3: 40000}
CREOSOTE_SURCHARGE_CENTS = {1: 0, 2: 6000, 3: 18000}
GLAZE_SURCHARGE_CENTS = 5000
TRIP_FEE_CENTS = {"A": 0, "B": 3500, "C": 7000}

# --- Invoice disposal fee (PRD §2.6 / §3.6) ---
DISPOSAL_FEE_RATE = 0.045

# --- Carbon monoxide safety thresholds (PRD §2.7 / §3.4) ---
CO_UNSAFE_PPM = 9
CO_CONDEMN_PPM = 70

# --- Scheduling (PRD §3.3) ---
TRAVEL_BUFFER_MINUTES = 30

# --- Reminders (PRD §3.8) ---
DEFAULT_CADENCE_MONTHS = 12

# --- Repair part catalog (PRD §3.5) ---
PART_CATALOG = {
    "CAP": ["CAP-STD", "CAP-SS"],
    "LINER": ["LNR-SS6", "LNR-AL"],
    "DAMPER": ["DMP-TOP", "DMP-THR"],
}

# --- Standard route-day window (2026-05-04, Unix seconds) used across scheduling tests ---
ROUTE_WINDOW_START = 1746342000
ROUTE_WINDOW_END = 1746374400
# A 90-minute on-site slot fully inside the window.
APPT_START = 1746345600
APPT_END_90 = 1746351000  # (1746351000 - 1746345600) / 60 == 90

# Server-startup default logical clock (PRD §2.5).
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"
