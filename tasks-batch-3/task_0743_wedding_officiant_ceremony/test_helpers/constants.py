"""Domain thresholds — numeric constants stated in the PRD's pricing, settlement,
and compliance rules (PRD Sections 2.6, 3.2, 3.6, 3.8).

Generic NON_EXISTENT_UUID comes from the framework. These constants are provided
for readability; each test asserts the literal expected value it is checking.
"""

# --- Travel surcharge tiers (PRD Section 3.2), cents ---
TRAVEL_TIER_CENTS = {
    "0-25": 0,
    "26-75": 15000,
    "76-150": 30000,
    "151+": 45000,
}

# --- Rush surcharge (PRD Section 3.2) ---
RUSH_THRESHOLD_DAYS = 30        # rush applies when days_until_ceremony_at_quote < 30 (strict)
RUSH_FEE_CENTS = 25000

# --- Interfaith surcharge (PRD Section 3.2) ---
INTERFAITH_SURCHARGE_CENTS = 20000

# --- Add-on line-item prices (PRD Section 3.2), cents ---
ADDON_PRICE_CENTS = {
    "UNITY_CANDLE": 5000,
    "HANDFASTING": 8000,
    "LIVESTREAM": 12000,
    "SAND_CEREMONY": 4000,
    "PREMIUM_SCRIPT": 5025,
    "BILINGUAL_CEREMONY": 8025,
}

# --- Gratuity (PRD Section 3.2) ---
GRATUITY_RATE = 0.18            # applied per line item, rounded half-up, then summed

# --- Cancellation settlement (PRD Section 3.8) ---
REFUND_TIER_GTE_90_PCT = 1.0
REFUND_TIER_30_TO_89_PCT = 0.5
REFUND_TIER_LT_30_PCT = 0.0
GOODWILL_PCT = 0.10            # service-initiated goodwill on quoted_subtotal_cents

# --- License return window (PRD Section 3.6) ---
LICENSE_RETURN_WINDOW_DAYS = 10

# --- Server startup logical clock default (PRD Section 2.5) ---
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"

# --- Test-fixture defaults (not PRD constants) ---
DEFAULT_BASE_PRICE_CENTS = 200000
DEFAULT_DEPOSIT_PCT = 0.30
