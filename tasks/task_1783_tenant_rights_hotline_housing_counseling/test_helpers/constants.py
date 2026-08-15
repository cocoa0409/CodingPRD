"""Domain thresholds and constants (PRD §2.5, §2.7, §3).

Numeric constants named in PRD prose: score tiers, tier cutoffs, follow-up
cadence counts, referral SLA hours, interpreter buffer, consent TTLs, the
training pass score, the deposit penalty multiplier, and the logical clock's
startup reading.
"""

# Logical clock startup reading (PRD §2.5).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Case priority score (PRD §3.6)
    "EV_TIER1_DAYS": 5,
    "EV_TIER1_POINTS": 50,
    "EV_TIER2_DAYS": 14,
    "EV_TIER2_POINTS": 30,
    "EV_TIER3_DAYS": 30,
    "EV_TIER3_POINTS": 15,
    "HAB_OVERDUE_POINTS": 15,
    "HAB_EGREGIOUS_POINTS": 25,
    "DEPOSIT_OVER_CAP_POINTS": 10,
    "MISS_PENALTY": 5,
    "ESCALATION_HISTORY_POINTS": 8,
    "SCORE_MIN": 0,
    "SCORE_MAX": 100,
    # Urgency tiers (PRD §3.6)
    "CRITICAL_MIN": 70,
    "ELEVATED_MIN": 40,
    # Interpreter buffered overlap (PRD §3.5)
    "BUFFER_MINUTES": 10,
    # Follow-up due window (PRD §3.7)
    "DUE_WINDOW_HOURS": 48,
    # Referral accept window after dispatch (PRD §3.8)
    "ACCEPT_WINDOW_HOURS": 96,
    # Training pass threshold (PRD §3.1)
    "TRAINING_PASS_SCORE": 80,
    # Deposit exposure (PRD §2.7, §3.6)
    "PENALTY_MULTIPLIER": 1.5,
    "DAYS_PER_YEAR_CENTI": 36500,
    # Analytics rate decimals (PRD §3.9)
    "RATE_DECIMALS": 4,
}

# Required follow-ups per urgency tier (PRD §3.6).
TIER_FOLLOWUPS = {"STANDARD": 1, "ELEVATED": 2, "CRITICAL": 3}

# Referral dispatch SLA hours per urgency tier (PRD §3.8).
SLA_HOURS = {"CRITICAL": 24, "ELEVATED": 72, "STANDARD": 168}

# Consent time-to-live in days per consent type (PRD §3.4).
TTL_DAYS = {
    "RECORDING": 7,
    "FOLLOW_UP": 30,
    "LEGAL_AID_RELEASE": 90,
    "DATA_SHARING": 365,
}

# Standard counselor certification expiry used across fixtures (safely after
# the default logical clock reading).
CERT_EXPIRY = "2027-01-01T00:00:00Z"

# A case-fact bundle that scores 75 (CRITICAL) at the default clock:
# eviction d=4 -> 50, habitability h=17 in (14, 28] -> 15, deposit over cap -> 10.
CRITICAL_CASE_FACTS = {
    "eviction_notice_date": "2026-08-05",
    "habitability_reported_at": "2026-07-15T00:00:00Z",
    "deposit_amount_cents": 200000,
    "monthly_rent_cents": 150000,
}
