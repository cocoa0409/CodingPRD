"""Domain thresholds and pricing constants from the PRD calculations (§3)."""

# ─── Park default tunable knobs (§3.1) ────────────────
PARK_DEFAULTS = {
    "GRIP_SOCK_PRICE_CENTS": 350,
    "MINOR_AGE_THRESHOLD": 18,
    "WALKIN_SURCHARGE_CENTS": 500,
    "PARTY_DEPOSIT_PCT": 0.25,
    "CANCELLATION_CUTOFF_MINUTES": 120,
    "TIMEZONE": "UTC",
}

# ─── Check-in window lead time (§3.6) ─────────────────
CHECKIN_LEAD_MINUTES = 30

# ─── Waiver validity (§3.4) ───────────────────────────
WAIVER_VALIDITY_DAYS = 365

# ─── Add-on catalog prices (§3.5) ─────────────────────
ADDON_PRICES = {
    "ARM_SLEEVES": 800,
    "LOCKER": 500,
    "FAST_PASS": 1500,
    "PHOTO_PKG": 2500,
}

# ─── Membership tier table (§3.7) ─────────────────────
MEMBERSHIP_TIERS = {
    "BRONZE": {"monthly_fee_cents": 2900, "discount_pct": 0.10, "included_visits": 2},
    "SILVER": {"monthly_fee_cents": 4900, "discount_pct": 0.15, "included_visits": 4},
    "GOLD": {"monthly_fee_cents": 7900, "discount_pct": 0.25, "included_visits": 8},
}
