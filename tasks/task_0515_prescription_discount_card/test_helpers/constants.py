"""Domain constants — numeric and string values fixed by PRD calculation rules."""

# Gold membership fee resolution (PRD §3.5).
GOLD_FEES = {
    "INDIVIDUAL_FEE_CENTS": 999,
    "FAMILY_FEE_CENTS": 1999,
    "MAX_FAMILY_COVERED": 5,
}

# Membership coverage-window adjacency buffer, in seconds (PRD §3.5).
MEMBERSHIP_BUFFER_SECONDS = 86400

# Mail-order quantity bounds (PRD §3.10).
MAIL_ORDER_MIN_QTY = 1
MAIL_ORDER_MAX_QTY = 3

# Coupon credential constants (PRD §3.6).
COUPON_CREDENTIALS = {
    "NETWORK_BIN": "610279",
    "GOLD_PCN": "GDX",
    "STANDARD_PCN": "STD",
    "GOLD_GROUP": "GOLDRX",
    "STANDARD_GROUP": "DISCRX",
}

# Server startup default for the logical clock (PRD §2.9).
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# Standard test clock used by most fixtures (mid-window relative to default quotes).
TEST_CLOCK_UTC = "2026-05-15T00:00:00Z"

# Canonical drug NDC used across fixtures.
ATORVA_NDC = "00071015523"

# Pagination bounds (PRD §2.3).
PAGINATION = {"limit_default": 10, "limit_min": 1, "limit_max": 100, "offset_min": 0}
