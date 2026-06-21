"""Domain constants from SCAFFOLD.yaml §constants_reference and §1.3."""

MIN_OFFER_VALUE = 50000          # dollars; AVM must be >= this to issue an offer
EST_CONCESSION_PCT = "0.01"      # provisional concession estimate fraction
OFFER_TTL_DAYS = 5               # offer validity from issued_at
REPAIR_CREDIT_CAP_PCT = "0.10"   # repair credit cap as fraction of avm_value_snapshot
RETRADE_CAP_PCT = "0.03"         # max re-trade as fraction of avm_value_snapshot
LEASEBACK_DAILY_PCT = "0.0004"   # leaseback daily rate fraction of effective AVM
MAX_LEASEBACK_DAYS = 60          # leaseback nights cap
MIN_CLOSE_LEAD_DAYS = 7          # earliest close_date relative to now
MAX_CLOSE_WINDOW_DAYS = 90       # latest close_date relative to now
INSPECTION_LEAD_DAYS = 3         # inspection window opens this many days before close
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"

# Default field values
DEFAULT_SERVICE_FEE_PCT = "0.05"
DEFAULT_RESALE_COMMISSION_PCT = "0.03"

# Enum domains
PAYOUT_METHODS = ("ACH", "WIRE")
CONDITION_SCALE = ("EXCELLENT", "GOOD", "FAIR", "POOR")  # best -> worst
REPAIR_CATEGORIES = ("ROOF", "HVAC", "FOUNDATION", "COSMETIC", "OTHER")

ROLES = ("Seller", "PricingAnalyst", "OperationsAdmin")
