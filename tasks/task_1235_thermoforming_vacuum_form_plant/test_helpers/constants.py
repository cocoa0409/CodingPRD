"""Plant-wide domain constants from the PRD.

PRD section references:
- §2.5 logical clock startup reading and certificate semantics
- §2.6 measurement precision and plant-wide constants
- §3.3 prototype shot limit materialization
"""

# --- PRD §2.6 plant-wide constants ---
TRIM_ALLOWANCE_PCT = 0.18
SETUP_FEE = 250.00
REGRIND_VALUE_PCT = 0.60
PROTO_SHOT_LIMIT = 500
BOOTH_TURNOVER_MINUTES = 30

# Regrind blend caps by order cleanliness grade (PRD §2.6 / §3.5):
# INDUSTRIAL 40 percent, FOOD 15 percent, MEDICAL zero.
BLEND_CAP = {
    "INDUSTRIAL": 0.40,
    "FOOD": 0.15,
    "MEDICAL": 0.00,
}

# Cleanliness grade ranking (PRD §2.5): INDUSTRIAL < FOOD < MEDICAL.
GRADE_RANK = {
    "INDUSTRIAL": 1,
    "FOOD": 2,
    "MEDICAL": 3,
}

# Logical clock (PRD §2.5): the startup reading.
CLOCK_STARTUP_UTC = "2026-05-01T00:00:00Z"

# Standard certificate window used by fixtures: valid at the startup clock.
CERT_ISSUED_AT = "2026-04-01T00:00:00Z"
CERT_EXPIRES_AT = "2026-09-01T00:00:00Z"
CERT_BODY = "LabA"

# Segregation-of-duties operator identities (PRD §2.1: X-User-ID is opaque).
PLANNER_1 = "planner-1"
PLANNER_2 = "planner-2"
INSPECTOR_1 = "qi-1"
INSPECTOR_2 = "qi-2"

__all__ = [
    "TRIM_ALLOWANCE_PCT",
    "SETUP_FEE",
    "REGRIND_VALUE_PCT",
    "PROTO_SHOT_LIMIT",
    "BOOTH_TURNOVER_MINUTES",
    "BLEND_CAP",
    "GRADE_RANK",
    "CLOCK_STARTUP_UTC",
    "CERT_ISSUED_AT",
    "CERT_EXPIRES_AT",
    "CERT_BODY",
    "PLANNER_1",
    "PLANNER_2",
    "INSPECTOR_1",
    "INSPECTOR_2",
]
