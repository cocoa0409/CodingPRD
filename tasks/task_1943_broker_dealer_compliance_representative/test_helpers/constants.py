"""Domain thresholds and weights — numeric constants from the PRD's calculation rules."""

# Logical clock (PRD §2.5): startup default before any clock-set call.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

THRESHOLDS = {
    # PRD §3.5: reportable at >= 500000 cents claimed, or FORGERY/THEFT.
    "REPORT_THRESHOLD_CENTS": 500000,
    # PRD §3.5: award disclosure auto-created at >= 150000 cents paid.
    "AWARD_DISCLOSURE_THRESHOLD_CENTS": 150000,
    # PRD §3.2: posture escalates at >= 2 open HIGH findings on one inspection.
    "HIGH_FINDING_THRESHOLD": 2,
    # PRD §3.2: due-date pull-in window on posture escalation.
    "ESCALATION_WINDOW_DAYS": 90,
    # PRD §3.1/§3.6: standard and accelerated inspection cycles.
    "STANDARD_CYCLE_MONTHS": 12,
    "ACCELERATED_CYCLE_MONTHS": 6,
    # PRD §3.2: minimum gap after the last CLOSED inspection.
    "INSPECTION_MIN_GAP_DAYS": 300,
    # PRD §3.3/§3.5/§3.6/§3.8: 30-day windows.
    "REVIEW_WINDOW_DAYS": 30,
    "REPORT_WINDOW_DAYS": 30,
    "FILING_WINDOW_DAYS": 30,
    "ATTEST_WINDOW_DAYS": 30,
}

# PRD §3.3 provisional correspondence risk score weights.
CHANNEL_WEIGHT = {
    "EMAIL": 5,
    "PAPER_LETTER": 10,
    "SMS": 20,
    "SOCIAL_MEDIA": 25,
}
CORRESPONDENCE_CAP = 100
CORRESPONDENCE_FLAG_FLOOR = 70
CORRESPONDENCE_ESCALATION_APPROVE_CEILING = 30
CORRESPONDENCE_HEIGHTENED_BONUS = 30
CORRESPONDENCE_POINTS_PER_HIT = 10

# PRD §3.2 branch risk score weights.
RISK_WEIGHTS = {"HIGH": 15, "MEDIUM": 5, "LOW": 2}
RISK_SD_BONUS = 20
RISK_CAP = 100

# PRD §3.5 complaint provisional reserve rates.
ALLEGATION_RATE = {
    "FORGERY": 1.00,
    "THEFT": 1.00,
    "MISREPRESENTATION": 0.60,
    "UNAUTHORIZED_TRADING": 0.50,
    "SUITABILITY": 0.40,
    "OTHER": 0.25,
}
FINAL_RESERVE_CAP_MULTIPLE = 1.25

# PRD §3.4 PST supervisory fee.
PST_FEE_RATE = 0.025

TEST_DEFAULTS = {
    "REGION": "NE",
    "HIRE_DATE": "2021-01-01",
    "RECEIVED_DATE": "2026-08-02",
    "FINDING_DUE_DATE": "2026-09-01",
    "INSPECTION_SCHEDULED_DATE": "2026-08-10",
    "ACTIVITY_START_DATE": "2026-09-01",
    "DISCLOSURE_EVENT_DATE": "2026-08-01",
}
