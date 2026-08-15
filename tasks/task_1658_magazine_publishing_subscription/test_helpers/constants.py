"""Domain thresholds and shared constants from the PRD's calculation rules."""

# Logical clock (PRD §2.4): startup default before any set is exactly
# 2026-08-01T00:00:00Z; the server never falls back to wall-clock time.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
# A clock reading far beyond any term horizon used by the tests; renewal
# effort windows anchored to 2026-era issue schedules are unambiguously open.
FAR_FUTURE_UTC = "2030-01-01T00:00:00Z"

# Standard production calendar: every deadline is at or before the startup
# clock so the full issue pipeline is reachable without moving the clock.
STD_COVER_DATE = "2026-08-01T00:00:00Z"
STD_EDITORIAL_CLOSE_DATE = "2026-07-01T00:00:00Z"
STD_AD_CLOSE_DATE = "2026-07-05T00:00:00Z"
STD_SHIP_TO_PRINTER_DATE = "2026-07-10T00:00:00Z"
STD_MAIL_DATE = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Postal compliance (PRD §3.4)
    "PERIODICAL_PAID_RATIO_MIN_BPS": 5000,
    "PERIODICAL_AD_CONTENT_MAX_BPS": 7500,
    # Circulation audit qualification (PRD §3.8)
    "AUDIT_PAID_QUALIFICATION_MIN_BPS": 7000,
    "AUDIT_CONTROLLED_QUALIFICATION_MAX_BPS": 3000,
    # Gift credit (PRD §3.2)
    "GIFT_CREDIT_BPS": 1000,
    # Back-issue markup (PRD §3.7)
    "BACK_ISSUE_MARKUP_BPS": 15000,
    "BACK_ISSUE_MARKUP_AGE_MONTHS": 12,
    # Grace period (PRD §3.6)
    "GRACE_PERIOD_DAYS": 30,
    # Pagination (PRD §2.3)
    "PAGINATION_LIMIT_MIN": 1,
    "PAGINATION_LIMIT_MAX": 100,
    "PAGINATION_DEFAULT_LIMIT": 10,
}

# Cancellation refund rates in basis points (PRD §3.6).
REFUND_RATE_BPS = {
    "NO_ISSUES_SERVED": 10000,
    "ONE_TO_THREE_SERVED": 9000,
    "OVER_THREE_SERVED": 5000,
}

# Postal rate table (PRD §3.4): base cents per weight tier, then entry-point
# discount in basis points, plus the PERIODICAL controlled-copy surcharge.
POSTAL_BASE_RATE_TIERS = {
    "PERIODICAL": [(3.3, 28), (6.0, 41), (10.0, 58)],
    "STANDARD": [(3.3, 52), (6.0, 74)],
    "FIRST_CLASS": [(1.0, 68), (2.0, 92), (3.0, 116)],
}
POSTAL_OVERAGE_PER_OZ_CENTS = {"PERIODICAL": 7, "STANDARD": 11, "FIRST_CLASS": 24}
POSTAL_OVERAGE_TIER_START_OZ = {"PERIODICAL": 10.0, "STANDARD": 6.0, "FIRST_CLASS": 3.0}
ENTRY_POINT_DISCOUNT_BPS = {"ORIGIN": 0, "DDU": 2100, "DSCF": 1300, "SCF": 700}
CONTROLLED_COPY_SURCHARGE_BPS = 500

TEST_DEFAULTS = {
    "BASE_COVER_PRICE_CENTS": 599,
    "TERM_ISSUES": 12,
    "PRICE_PAID_CENTS": 1200,
    "AD_PAGES_SOLD": 5,
    "NEWSSTAND_BUFFER_COPIES": 50,
}
