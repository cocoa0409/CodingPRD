"""Domain constants pinned by SCAFFOLD.yaml / PRD.md."""
from decimal import Decimal

# --- fees (PRD 3.4) -----------------------------------------------------
PLATFORM_FEE_PCT = Decimal("0.05")
PROCESSING_FEE_PCT = Decimal("0.029")
PROCESSING_FEE_FIXED_CENTS = 30

# --- registration pricing (PRD 3.3) ------------------------------------
EARLY_BIRD_DISCOUNT_PCT = Decimal("0.20")

# --- matching (PRD 3.5) -------------------------------------------------
MIN_APPLIED_MATCH_CENTS = 1

# --- receipts (PRD 3.6) -------------------------------------------------
RECEIPT_NUMBER_PAD_WIDTH = 6

# --- refunds (PRD 3.7) --------------------------------------------------
REFUND_WINDOW_DAYS = 60

# --- payouts (PRD 3.10) -------------------------------------------------
MIN_PAYOUT_CENTS = 5000

# --- registration conflicts (PRD 3.3) ----------------------------------
REGISTRATION_BUFFER_MINUTES = 90

# --- progress reporting (PRD 3.8) --------------------------------------
BASIS_POINTS_SCALE = 10000
PERCENT_BP_DISPLAY_CAP = 20000

# --- reporting (PRD 3.9) ------------------------------------------------
REPORT_ROW_LIMIT = 1000

# --- pagination (PRD 2.3) ----------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- roles (PRD 2.1) ----------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_CAMPAIGN_MANAGER = "CampaignManager"
ROLE_FINANCE_REVIEWER = "FinanceReviewer"
ROLE_PARTICIPANT = "Participant"
ROLE_DONOR = "Donor"
ROLE_ANONYMOUS = "Anonymous"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_CAMPAIGN_MANAGER,
    ROLE_FINANCE_REVIEWER,
    ROLE_PARTICIPANT,
    ROLE_DONOR,
    ROLE_ANONYMOUS,
)

PUBLIC_READ_ROLES = list(ALL_ROLES)
