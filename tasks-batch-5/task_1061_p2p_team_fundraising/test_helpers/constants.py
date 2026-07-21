"""Domain thresholds and shared literals drawn from the PRD's stated rules."""

THRESHOLDS = {
    # Fees on a gift (PRD §3.4)
    "PLATFORM_FEE_PCT": 0.05,
    "PROCESSING_FEE_PCT": 0.029,
    "PROCESSING_FEE_FIXED_CENTS": 30,
    # Registration pricing (PRD §3.3)
    "EARLY_BIRD_DISCOUNT_PCT": 0.20,
    # Buffered registration conflict window, in minutes on each side (PRD §3.3)
    "REGISTRATION_BUFFER_MINUTES": 90,
    # Refund window (PRD §3.7)
    "REFUND_WINDOW_DAYS": 60,
    # Disbursement floor (PRD §3.10)
    "MIN_PAYOUT_CENTS": 5000,
    # Basis points (PRD §2.6, §3.8)
    "BASIS_POINTS_SCALE": 10000,
    "PERCENT_BP_DISPLAY_CAP": 20000,
    # Receipt numbering (PRD §3.6)
    "RECEIPT_NUMBER_PAD_WIDTH": 6,
    "RECEIPT_NUMBER_PREFIX": "RCPT-",
    # Defaults the PRD names explicitly
    "DEFAULT_PERSONAL_GOAL_CENTS": 10000,
    "MIN_DONATION_AMOUNT_CENTS": 100,
}

# The logical clock reads exactly this instant at server startup (PRD §2.5).
CLOCK_STARTUP_UTC = "2026-07-01T00:00:00Z"

TEST_DEFAULTS = {
    "CAMPAIGN_GOAL_CENTS": 1_000_000,
    "TEAM_GOAL_CENTS": 100_000,
    "EVENT_FEE_CENTS": 4000,
    "EVENT_CAPACITY": 10,
    "EVENT_STARTS_AT": "2026-09-12T14:00:00Z",
    "EVENT_ENDS_AT": "2026-09-12T16:00:00Z",
    "EARLY_BIRD_ENDS_AT": "2026-08-01T00:00:00Z",
    "POOL_STARTS_AT": "2026-07-01T00:00:00Z",
    "POOL_ENDS_AT": "2026-08-01T00:00:00Z",
}

# A syntactically valid UUID that never resolves to a row.
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"

# Opaque operator identifiers. Finance reviewers are compared to each other only.
REVIEWER_ONE_ID = "fr-reviewer-1"
REVIEWER_TWO_ID = "fr-reviewer-2"
PLATFORM_ADMIN_ID = "platform-admin-1"


def expected_fee_cents(amount_cents: int) -> int:
    """Fee on a gift: each component rounded half up on its own, then summed."""
    platform = _round_half_up(amount_cents * THRESHOLDS["PLATFORM_FEE_PCT"])
    processing = _round_half_up(amount_cents * THRESHOLDS["PROCESSING_FEE_PCT"])
    return platform + processing + THRESHOLDS["PROCESSING_FEE_FIXED_CENTS"]


def expected_net_cents(amount_cents: int, cover_fees: bool = False) -> int:
    """What the campaign nets from the gift itself."""
    if cover_fees:
        return amount_cents
    return amount_cents - expected_fee_cents(amount_cents)


def _round_half_up(value: float) -> int:
    """Round half up to whole cents, away from zero at exactly one half."""
    from decimal import ROUND_HALF_UP, Decimal

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
