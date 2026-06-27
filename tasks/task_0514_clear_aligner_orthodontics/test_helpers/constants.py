"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Case price calculation (PRD §3.5)
IN_OFFICE_SCAN_SURCHARGE_CENTS = 25000
LIGHT_MULT = 0.80
MODERATE_MULT = 1.00
COMPLEX_MULT = 1.35
LIGHT_TIER_MAX_STEPS = 14          # count <= 14 -> LIGHT
MODERATE_TIER_MAX_STEPS = 28       # 15..28 -> MODERATE; >= 29 -> COMPLEX
FLAT200_DISCOUNT_CENTS = 20000
WELCOME15_RATE = 0.15

# Refund calculation (PRD §3.11)
RESTOCK_FEE_CENTS = 7500

# Delinquency calculation (PRD §3.7)
DEFAULT_THRESHOLD = 3              # late_count >= 3 -> DEFAULTED
GRACE_DAYS = 5

# Refinement fee (PRD §3.9)
INCLUDED_REFINEMENTS = 1
REFINEMENT_FEE_CENTS = 30000

# Intake usability gate (PRD §3.3)
MIN_USABLE_QUALITY = 0.60

# Shipment EXPRESS buffer (PRD §3.8)
EXPRESS_BUFFER_HOURS = 24

# Logical clock (PRD §2.5)
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
