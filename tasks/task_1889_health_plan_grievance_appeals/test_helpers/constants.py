"""Domain thresholds — numeric constants from the PRD's calculations (§2.4, §3)."""

# Logical clock mandatory startup default (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Acknowledgement window: triage must occur within 24h of received_at (PRD §3.3).
    "ACK_WINDOW_HOURS": 24,
    # IRE forwarding window: referral within 72h of decided_at (PRD §3.6).
    "IRE_FORWARD_WINDOW_HOURS": 72,
    # Timeliness boundary: consumed <= window is timely (PRD §3.7).
    "TIMELY_BOUNDARY_PERCENT": 100.00,
    # CTM exposure tier boundaries (PRD §3.9).
    "TIER_LOW_MAX": 2,
    "TIER_MEDIUM_MAX": 5,
    # Reopening window for NEW_EVIDENCE / CLERICAL_ERROR (PRD §3.8).
    "REOPEN_WINDOW_DAYS": 180,
    # Duplicate-intake look-back window (PRD §3.2).
    "DUPLICATE_WINDOW_HOURS": 1,
    # Policy bounds (PRD §2.9).
    "RESOLUTION_HOURS_MAX": 720,
    "EXTENSION_HOURS_MAX": 336,
    "EFFECTUATION_HOURS_MAX": 720,
}

# Medical necessity scoring weights (PRD §3.4).
SCORING_WEIGHTS = {
    "W_SEVERITY": 0.35,
    "W_ACUITY": 0.25,
    "W_GUIDELINE": 0.20,
    "W_COMORBIDITY": 0.10,
    "W_FUNCTIONAL": 0.10,
}

# Notification content element weights (PRD §3.5); they sum to exactly 1.00.
ELEMENT_WEIGHTS = {
    "citation_of_criteria": 0.25,
    "appeal_rights": 0.25,
    "decision_rationale": 0.20,
    "expedited_availability": 0.10,
    "ire_notice": 0.10,
    "contact_information": 0.05,
    "language_assistance": 0.05,
}

TEST_DEFAULTS = {
    "RESOLUTION_HOURS_STANDARD": 720,
    "RESOLUTION_HOURS_EXPEDITED": 72,
    "EFFECTUATION_HOURS": 72,
    "EXTENSION_HOURS": 24,
}
