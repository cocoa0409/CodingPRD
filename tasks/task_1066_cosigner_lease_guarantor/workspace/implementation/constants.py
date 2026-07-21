"""Domain constants — all values traced to PRD.md / SCAFFOLD.yaml."""
from decimal import Decimal

# --- Roles (PRD 2.1) ---
KNOWN_ROLES = {
    "PlatformAdmin",
    "Underwriter",
    "ClaimsAdjuster",
    "RecoveryAgent",
    "ComplianceOfficer",
    "Landlord",
    "Applicant",
}

# --- Applicant underwriting (PRD 3.1) ---
CREDIT_FLOOR = 580
A_CREDIT, A_DTI = 720, Decimal("0.35")
B_CREDIT, B_DTI = 660, Decimal("0.45")
C_CREDIT, C_DTI = 600, Decimal("0.55")

# --- Guarantee fee / coverage (PRD 3.2 / 3.4) ---
COVERED_FRACTION = Decimal("0.90")
MAX_COVERAGE_MONTHS = 12
MIN_FEE_CENTS = 15000
MAX_FEE_CENTS = 500000
TIER_RATE = {
    "A": Decimal("0.05"),
    "B": Decimal("0.08"),
    "C": Decimal("0.12"),
    "D": Decimal("0.18"),
}
PROVISIONAL_TIER = "C"

# --- Affordability gate (PRD 3.4) ---
RENT_INCOME_MAX = Decimal("0.40")

# --- Portfolio exposure (PRD 2.7 / 3.5) ---
TIER_WEIGHT = {
    "A": Decimal("0.5"),
    "B": Decimal("0.8"),
    "C": Decimal("1.2"),
    "D": Decimal("2.0"),
}
POSTURE_WARN_FRACTION = Decimal("0.80")

# --- Agreement unit-overlap buffer (PRD 3.3) ---
UNIT_BUFFER_DAYS = 30

# --- Logical clock (PRD 2.10) ---
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"

# --- Enums ---
EMPLOYMENT_TYPES = {"SALARIED", "SELF_EMPLOYED", "RETIRED", "UNEMPLOYED"}
COMPLIANCE_REASONS = {"KYC_MISMATCH", "SANCTIONS_HIT", "FRAUD_SUSPECTED", "AUTO_DEFAULT_TRIGGER"}
