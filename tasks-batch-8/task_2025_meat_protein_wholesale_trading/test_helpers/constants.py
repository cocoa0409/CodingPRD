"""Domain thresholds and numeric constants (PRD §2.4, §3.4, §3.8)."""

# PRD §2.4 — the logical clock before any operator advances it.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD §3.4 — grade multipliers of the aging-adjusted lot market value.
GRADE_MULTIPLIERS = {
    "PRIME": 1.08,
    "CHOICE": 1.00,
    "SELECT": 0.94,
    "STANDARD": 0.90,
    "NO_ROLL": 0.85,
    "UNGRADED": 0.97,
}

# PRD §3.4 — age-band multipliers (boundary-inclusive at band start).
AGE_BAND_MULTIPLIERS = [
    (7, 1.00),    # age_days <= 7
    (14, 0.95),   # 8 <= age_days <= 14
    (21, 0.88),   # 15 <= age_days <= 21
    (None, 0.75),  # age_days >= 22
]

# PRD §3.8 — provisional credit percentages by claim type.
CLAIM_PROVISIONAL_PCT = {
    "TEMPERATURE_ABUSE": 0.60,
    "SPEC_NONCONFORMANCE": 0.50,
    "WEIGHT_SHORTAGE": 1.00,
    "QUALITY_DEFECT": 0.40,
}

# PRD §3.8 — final settlement liability cap and conditional freight allowance.
LIABILITY_CAP_PCT = 0.80
FREIGHT_ALLOWANCE_CENTS = 15_000

# PRD §3.8 — negotiation cap on offer rounds.
MAX_OFFER_ROUNDS = 3

# Common week anchors used across tests (Mondays).
WEEK_1 = "2026-08-03"
WEEK_2 = "2026-08-10"
WEEK_3 = "2026-08-17"
