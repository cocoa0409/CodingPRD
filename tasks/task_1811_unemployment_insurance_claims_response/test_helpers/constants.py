"""Domain thresholds and constants from PRD §2.6, §2.10, §3.4, §3.6, §3.7."""

# PRD §2.6 — the fixed 2026 federal holiday list used by deadline arithmetic.
FEDERAL_HOLIDAYS = [
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26",
    "2026-12-25",
]
END_OF_DAY = "17:00:00Z"

# PRD §2.5 — the logical clock's startup default.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# PRD §3.4 — documentation assembly score.
DOC_BASE_POINTS = {
    "WRITTEN_WARNING": 25,
    "SIGNED_POLICY": 20,
    "FINAL_INCIDENT_REPORT": 30,
    "ATTENDANCE_RECORD": 15,
    "PERFORMANCE_REVIEW": 10,
    "RESIGNATION_LETTER": 25,
    "OTHER": 5,
}
AUTHENTICATED_BONUS = 10
POST_HOC_PENALTY = 5
SUBMIT_SCORE_THRESHOLD = 40
SCORE_CAP = 100

# PRD §3.6 — protest evidence score.
PROTEST_BASIS_WEIGHT = {
    "CLAIMANT_NOT_SEPARATED": 50,
    "WRONG_EMPLOYER": 70,
    "ALREADY_PROTESTED": 30,
    "EXCEEDS_MAX_BENEFIT": 60,
    "DUPLICATE_LINE": 65,
}
DENIED_DETERMINATION_BONUS = 20
LATE_RESPONSE_PENALTY = 25
CONFIRMED_CODING_BONUS = 10
DISPUTED_CODING_PENALTY = 10
SUSTAIN_EVIDENCE_THRESHOLD = 60

# PRD §3.5 — hearing continuances.
CONTINUANCE_LIMIT = 3
REFEREE_BUFFER_MINUTES = 30

# PRD §3.1 — TPA oversight.
BREACH_SUSPEND_THRESHOLD = 3
REINSTATE_BREACH_RESET = 1
REMEDIATION_NOTE_MIN_CHARS = 20

# PRD §2.10 — compliance posture (inclusive thresholds, half-strike granularity).
WATCH_THRESHOLD_STRIKES = 2
SANCTIONED_THRESHOLD_STRIKES = 4
DENIED_PROTEST_STRIKE = 0.5

# PRD §3.7 — experience rating rate table (first row whose ceiling >= ratio).
RATE_TABLE = [
    {"max_ratio": -0.05, "rate_bps": 60},
    {"max_ratio": 0.00, "rate_bps": 120},
    {"max_ratio": 0.02, "rate_bps": 180},
    {"max_ratio": 0.04, "rate_bps": 270},
    {"max_ratio": 0.06, "rate_bps": 360},
    {"max_ratio": 0.08, "rate_bps": 450},
    {"max_ratio": 1.00, "rate_bps": 540},
]
WATCH_SURCHARGE_BPS = 20
SANCTION_SURCHARGE_BPS = 50
RATE_CAP_BPS = 540
DEFAULT_TAX_RATE_BPS = 270

# Common test timestamps (all relative to the 2026 calendar above).
TS = {
    "CLOCK_START": "2026-08-03T09:00:00Z",   # Monday
    "NOTICE": "2026-08-03T09:00:00Z",
    "NOTICE_WED": "2026-08-05T09:00:00Z",    # Wednesday
    "NOTICE_FRI": "2026-09-04T09:00:00Z",    # Friday (Labor Day 2026-09-07)
    "BENEFIT_YEAR_BEGIN": "2026-08-02T00:00:00Z",
    "LAST_DAY_WORKED": "2026-07-01T00:00:00Z",
    "DOC_PRE_NOTICE": "2026-07-01T00:00:00Z",
    "MAILED": "2026-08-05T09:00:00Z",
    "LATE_CLOCK": "2026-08-09T18:00:00Z",    # past a 5-day CALENDAR deadline
    "APPEAL_DEADLINE": "2026-09-04T17:00:00Z",
    "APPEAL_ONE_SEC_LATE": "2026-09-04T17:00:01Z",
    "ENGAGEMENT_FROM": "2026-01-01T00:00:00Z",
    "ENGAGEMENT_TO": "2026-12-31T23:59:59Z",
    "STMT_ISSUED": "2026-08-03T09:00:00Z",
    "QUARTER": "2026Q3",
}
