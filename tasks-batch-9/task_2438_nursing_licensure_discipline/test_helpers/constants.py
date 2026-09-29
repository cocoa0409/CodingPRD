"""Domain thresholds and pinned literals drawn from the PRD.

Everything here is either a board-configuration default (PRD §2.5), a fixed
instant of the logical clock (PRD §2.4), or a ladder index used by the sanction
arithmetic (PRD §3.8).
"""

# The logical clock reads exactly this instant before it is ever set (PRD §2.4).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_STAMP = "2026-08-01T00:00:00.000Z"

# Board configuration defaults (PRD §2.5).
BOARD_DEFAULTS = {
    "compact_member": False,
    "status": "ACTIVE",
    "ce_hours_required": 30.00,
    "ce_self_study_cap_hours": 12.00,
    "ce_in_service_cap_hours": 4.00,
    "ce_carry_over_cap_hours": 5.00,
    "practice_hours_required": 960,
    "practice_lookback_months": 60,
    "renewal_period_months": 24,
    "renewal_grace_period_days": 60,
    "lapse_after_grace_days": 90,
    "audit_sample_rate_bp": 500,
    "criminal_lookback_years": 7,
    "disqualifying_offense_codes": ["FEL-A", "SEX-1"],
    "renewal_base_fee_cents": 12000,
    "late_fee_tier1_cents": 5000,
    "late_fee_tier2_cents": 12000,
    "reinstatement_fee_cents": 25000,
    "failed_audit_surcharge_cents": 2500,
    "phi_authorization_required": True,
    "max_concurrent_custodian_holds": 2,
    "monitoring_clearance_gap_days": 90,
    "revocation_vote_threshold_bp": 6667,
    "majority_vote_threshold_bp": 5001,
}

# Pagination (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# The six-tier sanction ladder, index 1 through 6 (PRD §3.8).
SANCTION_TIER_INDEX = {
    "REPRIMAND": 1,
    "FINE": 2,
    "PROBATION": 3,
    "PRACTICE_RESTRICTION": 4,
    "SUSPENSION": 5,
    "REVOCATION": 6,
}

# Base sanction index by violation category (PRD §3.8).
VIOLATION_BASE_INDEX = {
    "PRACTICE_STANDARD": 1,
    "FRAUD": 3,
    "SUBSTANCE_USE": 3,
    "BOUNDARY_VIOLATION": 4,
    "CRIMINAL_CONDUCT": 5,
}

# Complaint states inside the open set used by encumbrance reconciliation
# (PRD §2.7).
OPEN_COMPLAINT_STATES = [
    "INVESTIGATION_OPEN",
    "EVIDENCE_COMPLETE",
    "ATD_OFFERED",
    "ATD_ACTIVE",
    "REFERRED_FOR_HEARING",
    "PROCEEDING_OPENED",
]

# Budgets that are hard-capped at three (PRD §3.2, §3.5, §3.8).
LIMITS = {
    "DEFICIENCY_CYCLES": 3,
    "AUDIT_DOC_REQUEST_CYCLES": 3,
    "CONTINUANCES": 3,
    "MISSED_SCREENS_BEFORE_SUSPENSION": 3,
    "QUORUM_MINIMUM": 3,
}

# Residency evidentiary weight, strongest first (PRD §3.3).
EVIDENCE_WEIGHT_ORDER = ["DRIVER_LICENSE", "TAX_RETURN", "VOTER_REGISTRATION"]

# A syntactically valid UUID that never identifies a stored row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_ALT = "00000000-0000-4000-8000-000000000009"

# Recurring test literals.
TEST_DEFAULTS = {
    "BOARD_STATE_CODE": "OH",
    "BOARD_NAME": "Ohio Board of Nursing",
    "SECOND_STATE_CODE": "MI",
    "SECOND_BOARD_NAME": "Michigan Board of Nursing",
    "PROGRAM_APPROVAL_EXPIRES_ON": "2032-01-01T00:00:00Z",
    "LICENSE_ISSUED_ON": "2026-08-01T00:00:00.000Z",
    "LICENSE_EXPIRES_ON": "2028-08-01T00:00:00.000Z",
    "CUSTODIAN_PRIMARY": "MERCY-GEN",
    "CUSTODIAN_SECONDARY": "ST-LUKE",
}
