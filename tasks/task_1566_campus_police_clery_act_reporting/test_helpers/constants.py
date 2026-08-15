"""Domain thresholds — numeric constants from PRD §2/§3 calculations."""

THRESHOLDS = {
    # PRD §3.3 / §3.7: passing score for CSA training (inclusive)
    "TRAINING_PASS_SCORE": 80,
    # PRD §3.6: decision deadline is reported_at + 48h
    "WARNING_DECISION_HOURS": 48,
    # PRD §3.6: dissemination deadline is authorized_at + 24h
    "DISSEMINATION_HOURS": 24,
    # PRD §3.6: reopen window is closed_at + 72h
    "REOPEN_WINDOW_HOURS": 72,
    # PRD §3.4: immediate-access window for inspection requests
    "INSPECTION_IMMEDIATE_WINDOW_DAYS": 60,
    # PRD §3.4: pending inspection requests due in 2 business days
    "INSPECTION_FULFILL_BUSINESS_DAYS": 2,
    # PRD §3.4: crime-log entry/disposition timeliness window
    "LOG_UPDATE_BUSINESS_DAYS": 2,
    # PRD §3.4: provisional elapsed-hours immediate window (60*24)
    "INSPECTION_IMMEDIATE_WINDOW_HOURS": 1440,
    # PRD §3.9: escalation threshold for program review penalty score
    "ESCALATION_SCORE_THRESHOLD": 100,
    # PRD §3.9: severity base weights
    "WEIGHT_LOW": 10,
    "WEIGHT_MEDIUM": 25,
    "WEIGHT_HIGH": 50,
}

# The logical clock starts here before any clock-control call (PRD §2.4).
# Rendered with three fractional digits to match PRD §2.5's created_at /
# updated_at wire format ("ISO 8601 UTC with three fractional digits").
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"
