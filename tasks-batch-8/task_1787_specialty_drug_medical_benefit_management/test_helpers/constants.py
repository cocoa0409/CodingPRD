"""Domain thresholds and pricing constants (PRD §2.4, §3.4-§3.8)."""

# Logical clock (PRD §2.4): startup value before any clock call.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

THRESHOLDS = {
    # Authorization validity: validity_end = validity_start + 180 days, closed (PRD §3.4)
    "AUTH_VALIDITY_DAYS": 180,
    # Redirection offers lapse more than thirty days after creation (PRD §3.5)
    "REDIRECTION_OFFER_DAYS": 30,
    # Claim dose tolerance: rejected when administered_mg x 10 > approved_dose_mg x 11 (PRD §3.6)
    "DOSE_TOLERANCE_NUMERATOR": 11,
    "DOSE_TOLERANCE_DENOMINATOR": 10,
    # Forecast horizon range (PRD §3.8)
    "HORIZON_YEARS_MIN": 1,
    "HORIZON_YEARS_MAX": 5,
    # In-line spend observation window (PRD §3.8)
    "INLINE_WINDOW_DAYS": 90,
}

PRICING = {
    # Six percent base add-on always applies (PRD §3.6)
    "BASE_ADDON_PCT": 0.06,
    # Two percent more when the claim lands on the accepted redirection site (PRD §3.6)
    "REDIRECTED_SITE_ADDON_PCT": 0.02,
    # Twenty percent member coinsurance (PRD §3.6)
    "COINSURANCE_PCT": 0.20,
}

# Common default calendar anchors used across setups (all >= the startup clock date).
DEFAULTS = {
    "RATE_EFFECTIVE_START": "2026-01-01",
    "AUTH_START_DATE": "2026-08-01",
    "SERVICE_DATE": "2026-08-01",
    "ASP_RATE_CENTS": 500,
    "MAX_ADMINISTRATIONS": 4,
    "DIAGNOSIS": "C50",
}
