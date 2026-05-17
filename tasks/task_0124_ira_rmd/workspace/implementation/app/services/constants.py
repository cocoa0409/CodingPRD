"""Constants drawn directly from scaffold §1.3."""
from __future__ import annotations

# ---- Contribution caps ----
REGULAR_CAP_CENTS = 700_000     # $7,000
CATCHUP_CAP_CENTS = 100_000     # $1,000
CATCHUP_AGE = 50

# ---- RMD ----
RMD_AGE = 73

UNIFORM_LIFETIME_TABLE: dict[int, float] = {
    73: 26.5,
    74: 25.5,
    75: 24.6,
    76: 23.7,
    77: 22.9,
    78: 22.0,
}

SINGLE_LIFE_TABLE: dict[int, float] = {
    40: 45.7,
    45: 41.0,
    50: 36.2,
    55: 31.6,
    60: 27.1,
    65: 22.9,
    70: 18.8,
}

# ---- Federal withholding ----
EARLY_PENALTY_AGE = 59          # strictly less than 59 => early adder
MANDATORY_NORMAL_RATE = 0.10
MANDATORY_RMD_RATE = 0.10
EARLY_ADDER = 0.10

# ---- Excess contribution penalty ----
EXCESS_PENALTY_RATE = 0.06      # 6% standard excess penalty
MISSED_RMD_PENALTY_RATE = 0.25  # SECURE 2.0 reduced excise
FORFEIT_PENALTY_RATE = 0.25     # SECURE 25% on inherited-IRA forfeit

# ---- Enumerations ----
TAX_STATUSES = ["SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD"]
ACCOUNT_TYPES = ["TRADITIONAL", "ROTH"]
ACCOUNT_STATUSES = ["OPEN", "FROZEN", "CLOSED"]

CONTRIBUTION_TYPES = ["REGULAR", "CATCHUP", "BACKDOOR_NONDEDUCTIBLE"]
CONTRIBUTION_STATUSES = ["POSTED", "REVERSED"]

DISTRIBUTION_REASONS = ["NORMAL", "EARLY", "RMD", "DEATH", "CONVERSION", "EXCESS_REMOVAL"]

CONVERSION_STATUSES = ["PENDING", "APPROVED", "REJECTED", "COMPLETED", "CANCELED"]

CLAIM_STATUSES = ["CLAIMED", "SUSPENDED", "DRAINED", "FORFEITED"]

FORM_SOURCE_TYPES = ["DISTRIBUTION", "EXCESS_PENALTY", "CONVERSION"]
FORM_BOX7_CODES = ["1", "2", "7", "4", "G", "8"]
FORM_STATUSES = ["ISSUED", "CORRECTED", "VOIDED"]

# ---- Roles (string constants used in routes) ----
ROLE_PARTICIPANT = "Participant"
ROLE_CUSTODIAN = "Custodian"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_AUDITOR = "Auditor"

# ---- Per-call contribution cap (PRD §3.3) ----
PER_CALL_CONTRIBUTION_CAP_CENTS = 1_000_000
