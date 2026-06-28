"""Domain thresholds — numeric constants from PRD calculations (§2.7, §3.4, §3.7, §3.8, §3.9)."""

# Emergency surcharge multiplier basis: 1 + 15% (PRD §3.3, §3.7).
EMERGENCY_SURCHARGE_PCT = 0.15

# Infestation risk score (PRD §3.4).
SEVERITY_FACTORS = {"MINOR": 1.0, "MODERATE": 2.0, "MAJOR": 3.5}
REGULATED_MULTIPLIER = 1.5
RISK_SCORE_CAP = 1000.0

# Relocation distance (PRD §3.6).
EARTH_RADIUS_MILES = 3958.8

# Warranty window (PRD §3.9).
WARRANTY_DAYS = 30

# Conserved-money / cancellation refund (PRD §3.7).
SANITATION_FEE_CENTS = 7500

# Technician-window-conflict buffer (PRD §3.8): 15 minutes each side.
TRAP_VISIT_BUFFER_MINUTES = 15

# Default logical clock before any /_clock/set_current_utc call (PRD §2.11).
DEFAULT_CLOCK_UTC = "2026-04-01T00:00:00Z"

THRESHOLDS = {
    "EMERGENCY_SURCHARGE_PCT": EMERGENCY_SURCHARGE_PCT,
    "REGULATED_MULTIPLIER": REGULATED_MULTIPLIER,
    "RISK_SCORE_CAP": RISK_SCORE_CAP,
    "EARTH_RADIUS_MILES": EARTH_RADIUS_MILES,
    "WARRANTY_DAYS": WARRANTY_DAYS,
    "SANITATION_FEE_CENTS": SANITATION_FEE_CENTS,
    "TRAP_VISIT_BUFFER_MINUTES": TRAP_VISIT_BUFFER_MINUTES,
}
