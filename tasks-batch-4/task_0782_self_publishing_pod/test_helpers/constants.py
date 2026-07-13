"""Domain thresholds — numeric constants from the PRD calculations (PRD 2.x/3.x)."""

# Logical clock (PRD 2.9): process-startup default instant.
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

# Print manufacturing cost (PRD 3.2).
PRINT_FIXED_CHARGE_CENTS = 85
PER_PAGE_RATE_CENTS = {"BW": 1.2, "STANDARD_COLOR": 7.0, "PREMIUM_COLOR": 10.0}
LARGE_TRIM_SURCHARGE_CENTS_PER_PAGE = 0.5
LARGE_TRIM_BAND = {"7x10", "8.5x11"}
MIN_PAGE_COUNT = 24

# Cover spine width (PRD 3.3).
PAPER_CALIPER_MM = {"WHITE": 0.0572, "CREAM": 0.0635, "COLOR": 0.0572}
SPINE_TOLERANCE_MM = 0.5

# Reserve release (PRD 3.9): reserve matures after exactly one period.
RESERVE_RELEASE_AFTER_PERIODS = 1

# Standard AMZ channel configuration reused across pricing/royalty scenarios.
AMZ_CHANNEL = {
    "name": "AMZ",
    "channel_type": "RETAIL",
    "supports_formats": ["PRINT", "EBOOK"],
    "ebook_high_rate": 0.70,
    "ebook_low_rate": 0.35,
    "ebook_rate_low_threshold_cents": 299,
    "ebook_rate_high_threshold_cents": 999,
    "delivery_fee_per_mb_cents": 15,
    "distribution_discount_standard": 0.40,
    "distribution_discount_expanded": 0.60,
    "returns_reserve_pct": 0.15,
    "min_list_price_cents": 99,
    "max_list_price_cents": 25000,
}

# IGS channel — PRINT-only, used for unsupported-format-type checks.
IGS_CHANNEL = {
    "name": "IGS",
    "channel_type": "LIBRARY",
    "supports_formats": ["PRINT"],
    "distribution_discount_standard": 0.53,
    "distribution_discount_expanded": 0.53,
    "returns_reserve_pct": 0.15,
    "min_list_price_cents": 599,
    "max_list_price_cents": 25000,
}
