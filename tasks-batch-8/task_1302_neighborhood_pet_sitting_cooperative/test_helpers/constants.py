"""Domain thresholds and numeric constants named in the PRD."""

# Logical clock default (PRD §2.6): before any set call the clock reads this instant.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Request duration bounds in hours (PRD §3.3).
    "MIN_DURATION_HOURS": 1,
    "MAX_DURATION_HOURS": 72,
    # Request expiry: four hours before start_at (PRD §3.3).
    "EXPIRY_LEAD_HOURS": 4,
    # Owner overdraft floor at posting (PRD §3.3).
    "MAX_OVERDRAFT_HOURS": 5.0,
    # Reliability score bounds and event deltas (PRD §2.5).
    "SCORE_INIT": 50,
    "SCORE_SETTLE_BONUS": 2,
    "SCORE_LATE_CANCEL": -8,
    "SCORE_INCIDENT_AT_FAULT": -15,
    "SCORE_ACCESS_LOST": -10,
    "SCORE_DISPUTE_ESCALATED": -25,
    "SCORE_MIN": 0,
    "SCORE_MAX": 100,
    "CLAIM_MIN_SCORE": 30,
    # Early-departure repricing rule (PRD §3.6).
    "EARLY_DEPARTURE_THRESHOLD": 0.25,
    "EARLY_DEPARTURE_CREDIT_RATE": 0.5,
    # Late sitter-cancel window and penalty fraction (PRD §3.4).
    "LATE_CANCEL_WINDOW_HOURS": 24,
    "LATE_CANCEL_PENALTY_FRACTION": 0.25,
    # Incident penalty fraction of credit_hours_settled (PRD §3.7).
    "INCIDENT_PENALTY_FRACTION": 0.5,
    # Removal eligibility: >= 2 at-fault incidents in trailing 365 days (PRD §3.1).
    "AT_FAULT_WINDOW_DAYS": 365,
    "AT_FAULT_THRESHOLD": 2,
    # Handoff earliness bound: not earlier than two hours before start (PRD §3.5).
    "HANDOFF_EARLIEST_HOURS": 2,
    # Joining grant posted on finalization (PRD §3.1).
    "JOINING_GRANT_HOURS": 10.0,
    # Reference and narrative minimum lengths (PRD §3.1, §3.7).
    "MIN_RELATIONSHIP_YEARS": 1,
    "MIN_ATTESTATION_CHARS": 20,
    "MIN_INCIDENT_DESCRIPTION_CHARS": 30,
    "MIN_DISPUTE_STATEMENT_CHARS": 40,
}

TEST_DEFAULTS = {
    "ADDRESS_BLOCK": "MAPLE-100",
    "VET_NAME": "Maple Vet Clinic",
    "VET_PHONE": "+15550911",
    "VET_ADDRESS": "12 Maple St",
    # Canonical 4-hour sit window used across scenarios.
    "SIT_START": "2026-09-10T10:00:00Z",
    "SIT_END": "2026-09-10T14:00:00Z",
}
