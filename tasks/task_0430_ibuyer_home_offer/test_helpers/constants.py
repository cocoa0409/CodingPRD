"""Domain thresholds — numeric constants from the iBuyer Home Offer PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Valuation / offer floor (PRD §3.2)
MIN_OFFER_VALUE = 50000

# Provisional concession estimate fraction (PRD §3.2)
EST_CONCESSION_PCT = 0.01

# Offer validity span in days from issued_at (PRD §3.2)
OFFER_TTL_DAYS = 5

# Repair-credit cap as fraction of avm_value_snapshot (PRD §3.5)
REPAIR_CREDIT_CAP_PCT = 0.10

# Inspection re-trade cap as fraction of avm_value_snapshot (PRD §3.6)
RETRADE_CAP_PCT = 0.03

# Lease-back daily rate fraction of effective AVM (PRD §3.5)
LEASEBACK_DAILY_PCT = 0.0004

# Lease-back nights cap (PRD §3.5)
MAX_LEASEBACK_DAYS = 60

# Close-date window relative to current logical clock (PRD §3.5)
MIN_CLOSE_LEAD_DAYS = 7
MAX_CLOSE_WINDOW_DAYS = 90

# Inspection window opens this many days before close (PRD §3.6)
INSPECTION_LEAD_DAYS = 3

# Offer default service-fee fraction (PRD §3.2)
DEFAULT_SERVICE_FEE_PCT = 0.05

# Resale default commission fraction (PRD §3.8)
DEFAULT_RESALE_COMMISSION_PCT = 0.03

# Logical-clock startup default (PRD §2.7)
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"
