"""Domain thresholds — numeric constants drawn from the PRD calculations.

These mirror the literal constants the PRD states for sizing, refund proration,
plan pricing, repair invoicing, compliance scoring, and fuel adequacy.
"""

# Load sizing (PRD §3.2)
POWER_FACTOR = 0.8
KW_QUANTUM = 0.25

# Warranty refund proration (PRD §3.7)
HOURS_PER_MONTH_EQUIV = 50
COVERAGE_VALUE_CENTS = 240000

# Maintenance plan pricing (PRD §3.6)
MONITORING_ADDON_CENTS = 6000
BUNDLE_DISCOUNT = 0.10
TIER1_KW = 14
TIER2_KW = 24
VISIT_PRICE_TIER1_CENTS = 18000
VISIT_PRICE_TIER2_CENTS = 26000
VISIT_PRICE_TIER3_CENTS = 34000

# Repair invoice (PRD §3.8)
TAX_RATE = 0.0875

# Compliance scoring & monitoring health (PRD §3.5)
EXERCISE_INTERVAL_DAYS = 7
HEALTH_THRESHOLD = 70

# Fuel BTU adequacy (PRD §3.3)
BTU_PER_KW = 10000

# Repair dispatch tech-load cap (PRD §3.8)
TECH_LOAD_CAP = 5

# Maintenance visit scheduling intervals (PRD §3.6)
VISIT_BUFFER_HOURS = 4
GRACE_DAYS = 7

# Registration bonus (PRD §3.4)
REGISTRATION_BONUS_MONTHS = 12

# Logical clock default (PRD §2.4)
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

THRESHOLDS = {
    "POWER_FACTOR": POWER_FACTOR,
    "KW_QUANTUM": KW_QUANTUM,
    "HOURS_PER_MONTH_EQUIV": HOURS_PER_MONTH_EQUIV,
    "COVERAGE_VALUE_CENTS": COVERAGE_VALUE_CENTS,
    "MONITORING_ADDON_CENTS": MONITORING_ADDON_CENTS,
    "BUNDLE_DISCOUNT": BUNDLE_DISCOUNT,
    "TIER1_KW": TIER1_KW,
    "TIER2_KW": TIER2_KW,
    "TAX_RATE": TAX_RATE,
    "EXERCISE_INTERVAL_DAYS": EXERCISE_INTERVAL_DAYS,
    "HEALTH_THRESHOLD": HEALTH_THRESHOLD,
    "BTU_PER_KW": BTU_PER_KW,
    "TECH_LOAD_CAP": TECH_LOAD_CAP,
    "VISIT_BUFFER_HOURS": VISIT_BUFFER_HOURS,
    "REGISTRATION_BONUS_MONTHS": REGISTRATION_BONUS_MONTHS,
}
