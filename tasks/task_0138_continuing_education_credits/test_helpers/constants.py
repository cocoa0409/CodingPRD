"""Domain thresholds — numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Audit-risk score weights (PRD §3.9): late +3, rejected +5, approved reciprocity +2,
# clamped to [0, 100].
AUDIT_RISK_WEIGHTS = {
    "W_LATE": 3,
    "W_REJECT": 5,
    "W_RECIP": 2,
    "SCORE_CEILING": 100,
}

# Board policy defaults applied when the field is omitted at creation (PRD §3.1).
BOARD_DEFAULTS = {
    "carryover_cap_hours": 10.0,
    "audit_cooldown_days": 365,
    "reminder_lead_days": 60,
}

# Common test fixture values reused across the suite.
TEST_DEFAULTS = {
    "total_required_hours": 30.0,
    "ethics_min": 4.0,
    "substance_min": 2.0,
    "cycle_length_months": 24,
    "clock_start": "2026-01-01T00:00:00Z",
    "cycle_start": "2026-01-01T00:00:00Z",
    "completed_at": "2026-02-01T00:00:00Z",
    "accredited_until": "2030-01-01T00:00:00Z",
}

# Fixed admin / auditor identities used for segregation-of-duties scenarios.
ADMIN_INITIATOR_ID = "admin-initiator"
AUDITOR_ID = "auditor-x"
