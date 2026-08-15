"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock (PRD §2.4): startup default before any set call.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Heat activity tiers (PRD §3.4): lower bounds inclusive, 1-decimal compare.
HEAT_DISTRICT_BREAKS = {"CAUTION": 80.0, "MODERATE": 84.0, "SEVERE": 87.0,
                        "EXTREME": 90.0}
HEAT_STATE_BREAKS = {"CAUTION": 82.0, "MODERATE": 86.0, "SEVERE": 89.0,
                     "EXTREME": 92.0}

# Lightning holds (PRD §3.4).
LIGHTNING_HOLD_MINUTES_DISTRICT = 30
LIGHTNING_HOLD_MINUTES_TOURNAMENT = 45
DEFAULT_LIGHTNING_RADIUS_MILES = 8.0

# Coverage requirement (PRD §3.3).
RESTRICTED_ROSTER_BUMP_AT = 4
ATTENDANCE_BUMP_AT = 1000
REQUIRED_TRAINER_CAP = 4
VENUE_BUFFER_MINUTES = 30

# Return-to-play (PRD §3.7): stage dwell.
RTP_STAGE_DWELL_HOURS = 24
RTP_MAX_STAGE = 6
RTP_PHYSICIAN_REVIEW_RECURRENCES = 2

# Referral due windows in days (PRD §3.6).
REFERRAL_DUE_DAYS = {"ROUTINE": 14, "URGENT": 3, "EMERGENT": 1}

# Guardian notification escalation (PRD §3.8).
NOTIFICATION_ESCALATE_HOURS = 24

# Injury close window (PRD §3.5).
INJURY_CLOSE_AFTER_DAYS = 30

# Validity windows (PRD §3.1).
PHYSICAL_DISTRICT_VALIDITY_MONTHS = 13
BASELINE_VALIDITY_MONTHS = 24

TEST_DEFAULTS = {
    "UNIT_COST_CENTS": 100,
    "PAR_LEVEL": 50,
    "REORDER_THRESHOLD": 15,
    "BUDGET_TOTAL_CENTS": 100000,
    "FISCAL_YEAR": 2026,
}
