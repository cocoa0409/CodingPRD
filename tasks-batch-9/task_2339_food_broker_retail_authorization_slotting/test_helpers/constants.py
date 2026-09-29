"""Domain constants for the Food Broker Authorization & Slotting API.

Every value here is stated in the PRD. Nothing is invented and nothing is
computed at import time from an implementation.
"""

# --- Logical clock (PRD 2.5) -------------------------------------------------
# "Before any call is made, the clock reads exactly 2026-08-01T00:00:00Z".
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# --- Retail chain policy defaults (PRD 3.1) ---------------------------------
DEFAULT_VOID_RATE_BASIS = "STORE_COUNT_BASIS"
DEFAULT_AT_RISK_VOID_RATE_BPS = 1500
DEFAULT_DEDUCTION_DISPUTE_WINDOW_DAYS = 90
DEFAULT_DEMO_CHANGEOVER_BUFFER_MINUTES = 30
DEFAULT_MAX_CONCURRENT_DEMOS = 2
DEFAULT_REVIEW_BLACKOUT_DAYS = 14

# --- Rates and money (PRD 2.6) ----------------------------------------------
BPS_DENOMINATOR = 10000
MAX_BPS = 10000

# --- Quote ladder (PRD 3.5) -------------------------------------------------
CREDIT_PER_FORECAST_UNIT_CENTS = 3
VOLUME_CREDIT_CAP_BPS = 4000
ADMIN_TIER_1_MAX_CENTS = 5000000
ADMIN_BPS_TIER_1 = 250
ADMIN_BPS_TIER_2 = 150

# --- Negotiation / calendar / dispute bounds ---------------------------------
MAX_NEGOTIATION_ROUNDS = 3          # PRD 3.5: at most three retailer counters
MAX_REVIEW_REOPENS = 1              # PRD 3.4: a review may be reopened at most once
MAX_REFILES = 2                     # PRD 3.9: two refiles allowed
MIN_SUBSTANTIATION_DOCS = 2         # PRD 3.9: at least two substantiation documents
MIN_AMORTIZATION_PERIODS = 1        # PRD 2.8 / 3.5
MAX_AMORTIZATION_PERIODS = 12
MIN_PRESENTATION_ITEMS = 1          # PRD 3.4: between one and five item identifiers
MAX_PRESENTATION_ITEMS = 5

# --- Catalog (PRD 3.3) ------------------------------------------------------
MIN_SHELF_LIFE_DAYS = 30
GTIN14_PREFIX = "00"

# --- Promotions (PRD 3.8) ---------------------------------------------------
FUNDING_TOLERANCE_BPS = 11000

# --- Post-audit recovery (PRD 3.9) ------------------------------------------
SHORTAGE_ALLOWANCE_BPS = 5000

# --- Credit posture (PRD 3.9) -----------------------------------------------
WATCH_RATIO_BPS = 5000
RESTRICTED_RATIO_BPS = 7500
WATCH_AT_RISK_COUNT = 1
RESTRICTED_AT_RISK_COUNT = 2

# --- Pagination (PRD 2.3) ---------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Category codes (PRD 3.1) -----------------------------------------------
CATEGORY_CODES = ["FROZEN_SNACKS", "DAIRY", "BEVERAGE", "SNACK_NUTS", "HBC"]
PRIMARY_CATEGORY = "FROZEN_SNACKS"


def compute_upc_check_digit(first_eleven: str) -> int:
    """GS1 mod-10 check digit, alternating weights beginning at three (PRD 3.3)."""
    assert len(first_eleven) == 11, "check digit is computed over the first eleven digits"
    total = 0
    for index, char in enumerate(first_eleven):
        weight = 3 if index % 2 == 0 else 1
        total += int(char) * weight
    return (10 - (total % 10)) % 10


def valid_upc(seed_digit: int) -> str:
    """Build a structurally valid 12-digit UPC-A from a single seed digit 1..9."""
    body = "0" + str(seed_digit) * 5 + "00000"
    return body + str(compute_upc_check_digit(body))


def gtin14_for(upc: str) -> str:
    """The case-level GTIN-14 the PRD requires: '00' followed by the item's own upc."""
    return GTIN14_PREFIX + upc


# Convenience UPCs used by fixtures; ascending numeric order matches ascending upc order.
UPC_1 = valid_upc(1)   # 011111000001
UPC_2 = valid_upc(2)   # 022222000002
UPC_3 = valid_upc(3)   # 033333000003
UPC_4 = valid_upc(4)
UPC_5 = valid_upc(5)

# Twelve digits, wrong final digit: fails the GS1 mod-10 check (PRD 3.3).
UPC_BAD_CHECK_DIGIT = UPC_1[:11] + str((int(UPC_1[11]) + 1) % 10)
