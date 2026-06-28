"""Domain constants pulled verbatim from SCAFFOLD §1.3 calculations / PRD §3."""
from decimal import Decimal

# Pricing
NINETY_MIN_MULTIPLIER = Decimal("1.4")
COUPLES_SURCHARGE_CENTS = 1500

# Deposits & fees
DEPOSIT_FLAT_CENTS = 2000

# Timing windows
CHECKIN_LEAD_MINUTES = 60
RESCHEDULE_CUTOFF_HOURS = 12
CANCEL_CUTOFF_HOURS = 24
NO_SHOW_GRACE_MINUTES = 15

# Member gating
CURRENT_WAIVER_VERSION = 1
NO_SHOW_SUSPEND_THRESHOLD = 3

# Billing cycle
CYCLE_LENGTH_DAYS = 30

ROLES = {"Member", "FrontDesk", "Admin"}
