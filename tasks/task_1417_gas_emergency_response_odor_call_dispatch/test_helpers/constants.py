"""Domain thresholds — numeric constants from PRD §2 and §3.

The canonical territory T1 used across tests:
P1=30, P2=60, P3=240, P4=1440 minutes; recurrence window 72h; cap 1,000,000c.
"""

# Logical clock default at server startup (PRD §2.4).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical territory T1 (PRD §3.1).
T1_THRESHOLDS = {
    "p1_threshold_minutes": 30,
    "p2_threshold_minutes": 60,
    "p3_threshold_minutes": 240,
    "p4_threshold_minutes": 1440,
    "recurrence_window_hours": 72,
    "repair_budget_cap_cents": 1_000_000,
}

# Severity score constants (PRD §3.5).
LEL_EVACUATION_THRESHOLD = 10.0
LEL_ACTION_THRESHOLD = 5.0
CO_HIGH_PPM = 70
CO_MODERATE_PPM = 35
AUTO_NOTIFY_SEVERITY = 80

# Dispatch selector (PRD §3.4).
MAX_ACTIVE_ASSIGNMENTS = 2

# Crew travel buffer in minutes (PRD §3.7).
TRAVEL_BUFFER_MINUTES = 30

# Labor quantum (PRD §3.7).
LABOR_QUANTUM_MINUTES = 15

# Provisional estimate matrix, in cents (PRD §3.7).
PROVISIONAL_MATRIX = {
    "OUTSIDE_COMPANY": {"P1": 150000, "P2": 90000, "P3": 45000, "P4": 20000},
    "INSIDE_CUSTOMER": {"P1": 0, "P2": 0, "P3": 0, "P4": 0},
    "SHARED": {"P1": 75000, "P2": 45000, "P3": 22500, "P4": 10000},
    "UNDETERMINED": {"P1": 60000, "P2": 60000, "P3": 60000, "P4": 60000},
}
