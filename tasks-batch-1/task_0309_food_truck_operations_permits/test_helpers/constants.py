"""Domain thresholds — numeric constants from the PRD's operability and pricing rules.

Generic NON_EXISTENT_UUID comes from the framework barrel export.
"""

# Operability soft-gate thresholds (PRD §2.5, §3.8).
THRESHOLDS = {
    "MIN_OPERATING_PSI": 20,        # propane soft gate S1: propane_psi >= 20
    "GENERATOR_SERVICE_HOURS": 100,  # generator soft gate S3: runtime strictly < 100
}

# Settlement discount + cancellation constants (PRD §2.8, §3.7).
PRICING = {
    "HAPPY_HOUR_PCT": 0.15,    # HAPPY_HOUR reduces a line by 15% (multiply by 0.85)
    "BULK10_PCT": 0.10,        # BULK10 reduces a qualifying line by 10% (multiply by 0.90)
    "BULK10_MIN_QTY": 10,      # BULK10 eligibility judged per line on quantity >= 10
    "CANCEL_CUTOFF_MINUTES": 120,  # full refund only if cancel strictly > 120 min before window_start
}

# A syntactically valid UUID that no created entity will ever own.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
