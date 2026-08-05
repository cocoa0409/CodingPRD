"""Domain thresholds and numeric constants from the PRD workflows (§2, §3)."""

# Logical clock startup default (PRD §2.5).
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Symptom severity per-domain weights (PRD §3.2).
DOMAIN_WEIGHT = {
    "VASOMOTOR": 1.0,
    "SLEEP": 0.833,
    "MOOD": 0.667,
    "GENITOURINARY": 0.75,
    "COGNITIVE": 0.6,
}

# Absolute-contraindication set (PRD §3.2).
ABSOLUTE_CONTRAINDICATIONS = {
    "BREAST_CANCER_HISTORY",
    "VTE_HISTORY",
    "UNDIAGNOSED_BLEEDING",
    "STROKE_HISTORY",
}

# Cash discount (PRD §3.8): cash pays 90% of allowed.
CASH_DISCOUNT_RATE = 0.10

# Temporal buffers (PRD §3.4).
COVERAGE_BUFFER_DAYS = 7
INTAKE_VALIDITY_DAYS = 90

# Adherence bands (PRD §3.6).
AT_RISK_FLOOR = 0.80
ADHERENT_FLOOR = 0.90

# Subscription monthly fees by tier (PRD §3.7), in cents.
MONTHLY_FEE_CENTS = {
    "ESSENTIAL": 3900,
    "PLUS": 7900,
}

# Test-side default slot bounds (arbitrary; the default clock date is 2026-05-01).
DEFAULT_SLOT_START = "2026-05-10T09:00:00Z"
DEFAULT_SLOT_END = "2026-05-10T10:00:00Z"
