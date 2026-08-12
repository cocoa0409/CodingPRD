"""Domain thresholds and fixed text, all quoted from the PRD prose."""

# ── The logical clock (PRD §2.4) ─────────────────────────────────────────────
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# ── Window / cutoff / hold (PRD §3.4, §3.5) ──────────────────────────────────
HOLD_TTL_MINUTES = 45
CUTOFF_EXTENSION_MINUTES = 120
CUTOFF_EXTENSION_MAX_COUNT = 1
WINDOW_UNIT_CAPACITY_DEFAULT = 240
WINDOW_BATCH_SLOT_CAPACITY_DEFAULT = 12
WINDOW_OVEN_HOURS_CAPACITY_DEFAULT = 18.0
CAPACITY_CONSTRAINED_UTILIZATION_PCT = 0.80

# ── Batching / production (PRD §2.9, §3.7) ───────────────────────────────────
BATCH_SLOT_UNITS = 24
OVEN_HOURS_PER_BATCH_SLOT = 1.5
DEFAULT_YIELD_UNITS_PER_SLOT = 24
SHORTFALL_CREDIT_MULTIPLIER = 1.00

# ── Pricing / tax (PRD §2.5, §3.3, §3.5) ─────────────────────────────────────
DOZEN_SIZE = 12
BAKERS_DOZEN_UNITS = 13
MIN_UNITS_PER_LINE = 1
MAX_UNITS_PER_LINE = 120
MAX_LINES_PER_ORDER = 12
TAX_RATE_BPS = 725

# ── Statutory envelope (PRD §2.8) ────────────────────────────────────────────
ANNUAL_GROSS_SALES_CAP_CENTS = 8_500_000
DEFAULT_CAP_YEAR = 2026
PERMITTED_DELIVERY_RADIUS_KM = 40.0
COTTAGE_FOOD_STATEMENT_TEXT = (
    "Made in a home kitchen that is not subject to routine state inspection."
)
CROSS_CONTACT_ADVISORY_TEXT = (
    "Made in a home kitchen that also handles wheat, egg, milk, soy, peanut "
    "and tree nuts."
)

# ── Allergen tree (PRD §3.2) ─────────────────────────────────────────────────
ALLERGEN_TREE_MAX_DEPTH = 5

# ── Handoff (PRD §3.8) ───────────────────────────────────────────────────────
PICKUP_GRACE_MINUTES = 90
MISSED_REBOOK_MAX = 1
FORFEIT_REFUND_PCT = 0.00
DELIVERY_MINIMUM_CENTS = 3500
DELIVERY_ZONE_TIER1_MAX_KM = 8.0
DELIVERY_ZONE_TIER2_MAX_KM = 20.0
DELIVERY_ZONE_TIER3_MAX_KM = 40.0
DELIVERY_FEE_TIER1_CENTS = 500
DELIVERY_FEE_TIER2_CENTS = 900
DELIVERY_FEE_TIER3_CENTS = 1400

# ── Club (PRD §3.6) ──────────────────────────────────────────────────────────
SKIP_DEADLINE_HOURS_BEFORE_CUTOFF = 24
SUBSCRIPTION_PAUSE_CAP_COUNT = 2
SUBSCRIPTION_RESERVE_UNIT_SHARE_PCT = 0.30
PREPAID_CYCLE_DISCOUNT_PCT = 0.10
PREPAID_DEPOSIT_CYCLES = 4
PAST_DUE_GRACE_HOURS = 72

# ── Money (PRD §3.9) ─────────────────────────────────────────────────────────
TIP_PCT_MAX = 0.30
TIP_FIXED_MAX_CENTS = 5000
CREDIT_EXPIRY_DAYS = 365
PAYOUT_PERIOD_DAYS = 14

# ── Reviews (PRD §3.10) ──────────────────────────────────────────────────────
REVIEW_WINDOW_DAYS = 21
BAKER_RESPONSE_WINDOW_DAYS = 14
RATING_ROLLUP_MIN_REVIEWS = 3
RATING_SCALE_MIN = 1
RATING_SCALE_MAX = 5


# ── Fixture defaults: the "Hearth and Crumb" scenario every test builds on ───
COOKIE_UNIT_PRICE_CENTS = 450
COOKIE_DOZEN_PRICE_CENTS = 4600
LOAF_UNIT_PRICE_CENTS = 900
LOAF_DOZEN_PRICE_CENTS = 9600
SCONE_UNIT_PRICE_CENTS = 400
SCONE_DOZEN_PRICE_CENTS = 4400
LOAF_OVEN_HOURS_PER_BATCH = 3.0
LOAF_YIELD_UNITS_PER_SLOT = 12

WINDOW_OPENS_AT = "2026-05-04T00:00:00Z"
WINDOW_CUTOFF_AT = "2026-05-06T12:00:00Z"
WINDOW_PRODUCTION_DATE = "2026-05-07T06:00:00Z"
WINDOW_HANDOFF_DATE = "2026-05-07T15:00:00Z"
WINDOW_HANDOFF_END_AT = "2026-05-07T19:00:00Z"

CLOCK_ORDERING_TIME = "2026-05-04T09:00:00Z"
CLOCK_HOLD_LAPSE_TIME = "2026-05-04T09:45:00Z"
CLOCK_AT_CUTOFF = "2026-05-06T12:00:00Z"
CLOCK_AT_PRODUCTION = "2026-05-07T06:00:00Z"
CLOCK_AT_HANDOFF = "2026-05-07T15:00:00Z"
# handoff_window_end_at 19:00 plus the 90-minute grace
CLOCK_AT_PICKUP_FORFEIT = "2026-05-07T20:30:00Z"

LOT_RECEIVED_AT = "2026-04-20T00:00:00Z"
LOT_EXPIRES_AT = "2026-12-01T00:00:00Z"

NONEXISTENT_WINDOW_ID = "11111111-2222-4333-8444-555555555555"
NONEXISTENT_ORDER_ID = "99999999-8888-4777-8666-555555555555"
NONEXISTENT_MENU_ITEM_ID = "abcdef01-2345-4678-89ab-cdef01234567"
NONEXISTENT_GENERIC_ID = "00000000-0000-4000-8000-000000000000"


def bakers_dozen_total_cents(quantity, unit_price_cents, dozen_price_cents):
    """PRD §3.3 PER_DOZEN_BAKERS: whole blocks of 13 at the dozen price, the
    remainder charged individually at the unit price."""
    blocks, remainder = divmod(quantity, BAKERS_DOZEN_UNITS)
    return blocks * dozen_price_cents + remainder * unit_price_cents


def per_unit_total_cents(quantity, unit_price_cents):
    """PRD §3.3 PER_UNIT: quantity multiplied by unit_price_cents."""
    return quantity * unit_price_cents


def line_tax_cents(line_total_cents, taxable):
    """PRD §3.5: 725 basis points on the line total, rounded half up, and 0 for
    a WHOLE_UNHEATED line."""
    if not taxable:
        return 0
    from decimal import Decimal, ROUND_HALF_UP

    raw = Decimal(line_total_cents) * Decimal(TAX_RATE_BPS) / Decimal(10_000)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def half_up(value):
    """Round a fractional cent figure half up to a whole cent."""
    from decimal import Decimal, ROUND_HALF_UP

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
