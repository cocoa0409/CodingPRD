"""Server configuration constants and named values from the scaffold."""
import os

PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

# Auth headers — see PRD §2.1 and SCAFFOLD §1.4 priority 1/2/3.
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Recognised role names — see SCAFFOLD §1.7.
ROLES = {
    "ClientUser",
    "Advisor",
    "ComplianceOfficer",
    "TaxAdmin",
    "system",
}

# Entity-backed roles: their X-User-ID must resolve to an existing entity.
ENTITY_BACKED_ROLES = {"ClientUser", "Advisor"}

# Pagination defaults — see SCAFFOLD §1.0.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Calculation constants — see SCAFFOLD §1.3.
W_LOSS = 1
W_VOL = 1
W_GROW = 1
W_LIQ = 1
W_EXP = 1
CONSERVATIVE_MAX = 10
MODERATE_MAX = 17
AGGRESSIVE_MAX = 25
AGE_BIAS_THRESHOLD = 55

SHORT_HORIZON_MAX = 5
MID_HORIZON_MAX = 15
LONG_HORIZON_MAX = 40

DRIFT_TRIGGER_PCT = 5.00
MIN_HARVEST_THRESHOLD_CENTS = 50000  # $500.00
WASH_WINDOW_DAYS = 30
LONG_TERM_DAY_THRESHOLD = 365
FORM_VOID_WINDOW_DAYS = 30
FRACTIONAL_SHARE_DECIMALS = 4

ASSET_CLASSES = ("US_EQUITY", "INTL_EQUITY", "US_BOND", "INTL_BOND", "CASH")
RISK_BANDS = ("CONSERVATIVE", "MODERATE", "AGGRESSIVE")
HORIZON_BANDS = ("SHORT", "MID", "LONG")
