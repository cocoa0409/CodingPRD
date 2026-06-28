"""Domain thresholds — numeric constants from the Banquet Event Order PRD calculations."""

# Setup-style seating factors (PRD §3.4). effective_capacity = floor(max_capacity * factor).
SETUP_FACTOR = {
    "ROUNDS": 0.6,
    "THEATER": 1.0,
    "CLASSROOM": 0.5,
    "RECEPTION": 0.8,
}

# Room rental is charged per STARTED hour (PRD §3.3).
MINUTES_PER_HOUR = 60

# Field defaults applied at event creation when omitted (PRD §3.2).
EVENT_DEFAULTS = {
    "overset_pct": 0.05,
    "service_charge_pct": 0.22,
    "gratuity_pct": 0.0,
    "sales_tax_pct": 0.08,
}

# Permitted ranges for the percentage fields (PRD §3.2).
PCT_RANGES = {
    "overset_pct": (0.0, 0.10),
    "service_charge_pct": (0.0, 0.30),
    "gratuity_pct": (0.0, 0.25),
    "sales_tax_pct": (0.0, 0.15),
}
