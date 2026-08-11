"""Domain thresholds — numeric constants taken from the PRD's calculations."""

# --- logical clock (PRD §2.4) -------------------------------------------------
CLOCK_STARTUP_UTC = "2026-05-01T00:00:00Z"

# --- removal SLA deadline (PRD §3.5) -----------------------------------------
METHOD_SLA_BUFFER_DAYS = {
    "WEB_FORM": 0,
    "EMAIL": 2,
    "POSTAL": 7,
    "PHONE": 3,
}
JURISDICTION_SLA_FLOOR_DAYS = {
    "US_CA": 45,
    "US_VA": 45,
    "EU": 30,
    "OTHER": 21,
}
ESCALATION_RESUBMIT_WINDOW_DAYS = 15
MAX_ESCALATIONS = 2
BROKER_WINDOW_MIN_DAYS = 5
BROKER_WINDOW_MAX_DAYS = 90

# --- hygiene score (PRD §3.7) -------------------------------------------------
HYGIENE_BASE_SCORE = 100
HYGIENE_WEIGHTS = {
    "BREACHED_PASSWORD": 25,
    "WEAK_PASSWORD": 18,
    "REUSED_PASSWORD": 12,
    "STALE_PASSWORD": 7,
}
HYGIENE_PENALTY_CAP = 70
HYGIENE_TWO_FACTOR_MULTIPLIER = 0.60
HYGIENE_NO_TWO_FACTOR_MULTIPLIER = 1.00
HYGIENE_BAND_STRONG_MIN = 80
HYGIENE_BAND_MODERATE_MIN = 60
HYGIENE_BAND_WEAK_MIN = 40

# --- breach alert severity (PRD §3.6) ----------------------------------------
BREACH_POINTS = {
    "EMAIL_ADDRESS": 10,
    "PHONE_NUMBER": 15,
    "PHYSICAL_ADDRESS": 8,
    "PASSWORD_HASH": 30,
    "FINANCIAL_ACCOUNT": 40,
    "SSN": 45,
}
IDENTIFIER_MATCH_BONUS_POINTS = 5
SENSITIVE_IDENTIFIER_BONUS_POINTS = 15
OPEN_BREACHED_PASSWORD_ESCALATION_POINTS = 10
SEVERITY_BAND_CRITICAL_MIN = 60
SEVERITY_BAND_HIGH_MIN = 45
SEVERITY_BAND_MEDIUM_MIN = 25
SEVERITY_ORDINALS = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

# --- broker compliance (PRD §3.9) --------------------------------------------
BROKER_COMPLIANCE_BASE_SCORE = 100
COMPLIANCE_PENALTY_PER_REAPPEARANCE = 8
COMPLIANCE_PENALTY_PER_EXPIRED_REQUEST = 12
COMPLIANCE_PENALTY_PER_REJECTED_REQUEST = 5
COMPLIANCE_BONUS_PER_ONTIME_COMPLETION = 3
COMPLIANCE_SCORE_FLOOR = 0
COMPLIANCE_SCORE_CEILING = 100
COMPLIANCE_WINDOW_DAYS = 30
COMPLIANCE_REPORT_TOP_N = 5

# --- billing (PRD §3.8, §3.9) -------------------------------------------------
CYCLE_LENGTH_DAYS = 30
PRORATION_DAY_BASIS = 30
ADDON_PRORATION_DAY_BASIS = 30
LOYALTY_TIER_1_THRESHOLD_CENTS = 1500
LOYALTY_TIER_1_RATE = 0.02
LOYALTY_TIER_2_THRESHOLD_CENTS = 3000
LOYALTY_TIER_2_RATE = 0.05
LOYALTY_TIER_3_THRESHOLD_CENTS = 5000
LOYALTY_TIER_3_RATE = 0.08

# --- intervals and caps -------------------------------------------------------
REAPPEARANCE_COOLOFF_DAYS = 45
RESCAN_MIN_INTERVAL_DAYS = 7
MAX_SCAN_RETRIES = 2
SEAT_REBIND_COOLOFF_HOURS = 72
REQUEST_REOPEN_BUFFER_HOURS = 24
MAX_IDENTIFIERS_PER_PROFILE = 8
IDENTITY_DOC_MIN_LEAD_SECONDS = 1

# --- reusable plan shapes for fixtures ----------------------------------------
FAMILY_PLAN = {
    "tier": "FAMILY",
    "name": "Family Shield",
    "monthly_fee_cents": 2200,
    "max_members": 4,
    "profile_quota_per_cycle": 4,
    "scan_quota_per_cycle": 12,
    "removal_quota_per_cycle": 60,
    "per_member_removal_subcap": 25,
}
SOLO_PLAN = {
    "tier": "SOLO",
    "name": "Solo Shield",
    "monthly_fee_cents": 1200,
    "max_members": 1,
    "profile_quota_per_cycle": 1,
    "scan_quota_per_cycle": 4,
    "removal_quota_per_cycle": 20,
    "per_member_removal_subcap": 20,
}
FAMILY_PLUS_PLAN = {
    "tier": "FAMILY_PLUS",
    "name": "Family Plus",
    "monthly_fee_cents": 3400,
    "max_members": 6,
    "profile_quota_per_cycle": 8,
    "scan_quota_per_cycle": 24,
    "removal_quota_per_cycle": 120,
    "per_member_removal_subcap": 40,
}
