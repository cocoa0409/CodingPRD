"""Domain thresholds — numeric constants named by the PRD."""

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    "APPEAL_WINDOW_DAYS": 14,
    "PRE_REVIEW_FRESHNESS_HOURS": 72,
    "MIN_SCREENSHOTS_PER_CLASS": 2,
    "CREDENTIAL_EXPIRY_WARNING_HOURS": 168,
    "PROVISIONAL_CONFIDENCE_FLOOR": 0.8000,
    "DISCLOSURE_PASS_THRESHOLD": 0.9500,
    "POSTURE_INDEX_FLOOR": 90.00,
    "ACCEPT_NO_CHANGE_SEVERITY_CEILING": 6.00,
    "EXPEDITE_STANDING_FLOOR": 60.00,
    "EXPEDITE_CREDITS_PER_WINDOW": 2,
    "BASE_SLA_HOURS": 48,
    "PHASE_COUNT": 7,
    "MIN_PHASE_DWELL_HOURS": 24,
    "ROLLBACK_COOLDOWN_HOURS": 72,
    "POOL_MAX_CONCURRENT_SLOTS": 10,
    "ROLLING_WINDOW_DAYS": 365,
    "RETAINED_SUBSCRIBER_MONTHS": 12,
}

# severity_weight derived from the guideline category
SEVERITY_WEIGHTS = {"SAFETY": 5, "PRIVACY": 4, "COMMERCE": 3, "LEGAL": 3, "DESIGN": 1}

# remediation_grace_days derived from the guideline category
REMEDIATION_GRACE_DAYS = {
    "SAFETY": 14,
    "PRIVACY": 30,
    "COMMERCE": 45,
    "LEGAL": 30,
    "DESIGN": 60,
}

# compliance factor by self_review_status, used by feature_compliance_index
COMPLIANCE_FACTORS = {
    "PASSED": 1.0,
    "WAIVED_BY_PLATFORM": 1.0,
    "STALE": 0.5,
    "IN_PROGRESS": 0.25,
    "NOT_STARTED": 0.0,
    "FAILED": 0.0,
}

# declared rating bands
RATING_BANDS = [0, 4, 9, 12, 17, 18]

# intensity level -> band
INTENSITY_BAND = {0: 0, 1: 9, 2: 12, 3: 17}

# fixed priority order of the six intensity dimensions, as the driving-dimension label
AGE_RATING_DIMENSION_ORDER = [
    "VIOLENCE",
    "SEXUAL_CONTENT",
    "DRUGS_ALCOHOL",
    "GAMBLING_SIMULATED",
    "HORROR",
    "PROFANITY",
]

# the questionnaire answer keys for the six intensity dimensions
ANSWER_INTENSITY_KEYS = [
    "violence",
    "sexual_content",
    "profanity",
    "gambling_simulated",
    "drugs_alcohol",
    "horror",
]

# the questionnaire answer keys for the five declared booleans
ANSWER_BOOLEAN_KEYS = [
    "unrestricted_web_access",
    "user_generated_content",
    "ugc_moderation_enabled",
    "real_money_gambling",
    "contests",
]

# driving-dimension label for each intensity answer key
DIMENSION_LABEL_BY_ANSWER_KEY = {
    "violence": "VIOLENCE",
    "sexual_content": "SEXUAL_CONTENT",
    "profanity": "PROFANITY",
    "gambling_simulated": "GAMBLING_SIMULATED",
    "drugs_alcohol": "DRUGS_ALCOHOL",
    "horror": "HORROR",
}

# unmatched-finding penalties for the disclosure accuracy scores
DISCLOSURE_SEVERITY_PENALTIES = {"CRITICAL": 40, "MAJOR": 20, "MINOR": 5}
OVER_DISCLOSURE_PENALTY = 2

# standing score penalties and credits
STANDING_SEVERITY_PENALTIES = {"CRITICAL": 12, "MAJOR": 6, "MINOR": 2}
STANDING_APPEAL_CREDIT = 3
STANDING_CLEAN_ROLLOUT_CREDIT = 2

# review priority
SLA_HOURS_BY_BAND = {"EXPEDITED": 12, "HIGH": 24, "NORMAL": 48, "LOW": 96}
HIGH_BAND_FLOOR = 70.00
NORMAL_BAND_FLOOR = 40.00

# commission settlement
STANDARD_RATE = 0.30
SMALL_BUSINESS_RATE = 0.15
RETAINED_SUBSCRIBER_RATE = 0.15
EXTERNAL_LINK_DISCOUNT = 0.03

# the seven fixed audience shares, at indices 0 through 6
PHASE_PCTS = [1.00, 2.00, 5.00, 10.00, 20.00, 50.00, 100.00]

# device classes required by platform
REQUIRED_DEVICE_CLASSES = {"IOS": ["PHONE_65", "TABLET_129"], "ANDROID": ["PHONE_65"]}

TEST_DEFAULTS = {
    "MEMBERSHIP_PAID_THROUGH": "2027-08-01T00:00:00Z",
    "CERT_NOT_BEFORE": "2026-07-01T00:00:00Z",
    "CERT_NOT_AFTER": "2027-07-01T00:00:00Z",
    "WINDOW_STARTS_AT": "2026-08-01T00:00:00Z",
    "WINDOW_ENDS_AT": "2026-12-31T00:00:00Z",
    "EVIDENCE_REF": "https://evidence.northwind.example/acct-deletion.pdf",
}
