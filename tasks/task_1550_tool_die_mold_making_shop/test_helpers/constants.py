"""Domain thresholds and pricing constants (PRD §2.4, §2.8, §2.9, §3.3-§3.9)."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Quote price construction (PRD §3.3).
CLASS_BASE_CENTS = {
    "CLASS_101": 12_000_000,
    "CLASS_102": 9_000_000,
    "CLASS_103": 6_500_000,
    "CLASS_104": 4_000_000,
    "CLASS_105": 1_800_000,
}
CAVITY_RATE_CENTS = {
    "CLASS_101": 800_000,
    "CLASS_102": 650_000,
    "CLASS_103": 500_000,
    "CLASS_104": 350_000,
    "CLASS_105": 200_000,
}
COMPLEXITY_RATE_CENTS = 150_000
STANDARD_LEAD_WEEKS = {
    "CLASS_101": 20, "CLASS_102": 16, "CLASS_103": 12, "CLASS_104": 10, "CLASS_105": 6,
}
MIN_LEAD_WEEKS = {
    "CLASS_101": 12, "CLASS_102": 10, "CLASS_103": 8, "CLASS_104": 6, "CLASS_105": 3,
}
# PRD §3.3 step 2: "four hundredths per compression week, capped at forty hundredths".
SURCHARGE_PER_COMPRESSION_WEEK = 0.04
SURCHARGE_CAP = 0.40
EXPEDITED_MULTIPLIER = 1.10
CONTINGENCY_PCT = {"BUDGETARY": 0.15, "FIRM": 0.05}
VALIDITY_DAYS = {"BUDGETARY": 14, "FIRM": 30}

# Milestone billing schedule (PRD §3.4/§3.5).
BILLING_PCT = [20, 25, 25, 15, 10, 5]
MILESTONE_CODES = [
    "DESIGN_COMPLETE", "MATERIAL_STAGED", "MACHINING_COMPLETE",
    "T1_TRYOUT_DONE", "BUYOFF_SIGNED", "DELIVERY_ACCEPTED",
]

# ECO impact reprice (PRD §3.7).
CLASS_LABOR_RATE_CENTS = {
    "CLASS_101": 14_500, "CLASS_102": 13_500, "CLASS_103": 12_500,
    "CLASS_104": 11_500, "CLASS_105": 10_500,
}
MATERIAL_MARKUP = 1.15
PENALTY_FREE_EXTENSION_WEEKS = 2
PENALTY_PCT_PER_WEEK = 0.01

# Warranty (PRD §3.4 shot limits by class; §3.9 credit variants).
WARRANTY_SHOT_LIMIT = {
    "CLASS_101": 1_000_000, "CLASS_102": 500_000, "CLASS_103": 250_000,
    "CLASS_104": 100_000, "CLASS_105": 10_000,
}
WARRANTY_DAYS = 730

# Scheduling (PRD §2.9).
COOLDOWN_BUFFER_HOURS = 4
WEEKLY_CAPACITY_HOURS = 45.0

# Lien / credit (PRD §2.8, §3.8).
SHIP_OUTSTANDING_PCT = 0.15
NET_TERMS_DAYS = 30
GRACE_DAYS = 10

# Segregation-of-duties fixture convention: invoices are issued by the fin-a
# FinanceAdmin identity and payments are recorded by the fin-b identity.
FINANCE_ISSUER_USER_ID = "fin-a"
FINANCE_PAYER_USER_ID = "fin-b"
