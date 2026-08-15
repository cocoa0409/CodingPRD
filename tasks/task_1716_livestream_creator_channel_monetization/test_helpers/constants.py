"""Domain thresholds and shared values — numeric constants from the PRD."""

# Fixed startup reading of the logical clock (PRD logical-clock section).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Clock reading used to settle August events at the next month boundary.
SEPTEMBER_CLOCK_ISO = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Month-end volume rebate cliff and size (PRD revenue-recognition section).
    "VOLUME_REBATE_THRESHOLD_CENTS": 5_000_000,
    "VOLUME_REBATE_BPS": 250,
    # W8-series withholding share per swept event.
    "WITHHOLDING_BPS_W8": 3000,
    # Transfer-fee tiers keyed on the pre-fee post-withholding snapshot.
    "FEE_TIER_HIGH_CENTS": 1_000_000,
    "FEE_TIER_MID_CENTS": 100_000,
    "FEE_BPS_HIGH": 25,
    "FEE_BPS_MID": 50,
    "FEE_BPS_LOW": 100,
    # Strike weights and posture gates.
    "WEIGHT_MINOR": 1,
    "WEIGHT_MAJOR": 2,
    "WEIGHT_SEVERE": 3,
    "SUSPENSION_WEIGHT": 3,
    "TRUST_PENALTY_PER_WEIGHT_BP": 2500,
    # Strike lifecycle windows.
    "STRIKE_EXPIRY_DAYS": 90,
    "APPEAL_WINDOW_DAYS": 14,
    "APPEAL_ROUND_CAP": 2,
    # Payout retry cap.
    "RETRY_CAP": 3,
    # Moderation shape rules and progressive discipline.
    "MAX_TIMEOUT_MINUTES": 10_080,
    "BAN_MIN_PRIOR_TIMEOUTS": 2,
    # Merch perk fulfillment SLA in days.
    "PERK_SLA_DAYS": 14,
    # Stream start grace in minutes; simulcast approval buffer in hours.
    "STREAM_START_GRACE_MINUTES": 30,
    "SIMULCAST_BUFFER_HOURS": 24,
    # Channel onboarding defaults.
    "DEFAULT_PAYOUT_THRESHOLD_CENTS": 10_000,
    # Platform fee on sponsorship money booked at deal activation.
    "SPONSORSHIP_PLATFORM_FEE_BPS": 1000,
}

TEST_DEFAULTS = {
    "PAYOUT_SCHEDULE": "MONTHLY",
    "TIER_PRICE_CENTS": 5_000,
    "TIER_REVENUE_SHARE_BPS": 5_000,
    "DEAL_VALUE_CENTS": 100_000,
    "DEAL_FLIGHT_START": "2026-08-05T00:00:00Z",
    "DEAL_FLIGHT_END": "2026-09-30T00:00:00Z",
}

# Recurring opaque operator identities used across the suite. The strike
# issuer id matters wherever segregation of duties is exercised.
TRUST_AGENT_ISSUER_ID = "trust_nina"
APPEALS_OFFICER_ID = "appeals_omar"
SPONSOR_ACME_ID = "sponsor_acme"
