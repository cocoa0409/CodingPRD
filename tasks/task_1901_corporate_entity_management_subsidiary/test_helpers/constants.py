"""Domain thresholds and calculation constants from the PRD.

PRD 3.7 franchise tax: 5000 free shares, 10000-share blocks at 8500 cents,
base 17500, cap 2000000, nonprofit flat 2500.
PRD 3.7 late penalty: daily rates 0.00037 (tax) and 0.00041 (report fee).
PRD 3.13 posture: hard-overdue threshold is 30 days past grace end.
PRD 3.10 certificates: validity is issued_date + 90 calendar days.
"""

# Logical clock startup value (PRD 3.15): before any clock-adjustment call the
# logical clock reads exactly 2026-08-01T00:00:00Z.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# Franchise tax (PRD 3.7)
TAX_BASE_CENTS = 17500
FREE_SHARES = 5000
SHARE_BLOCK_SIZE = 10000
PER_BLOCK_CENTS = 8500
TAX_CAP_CENTS = 2000000
NONPROFIT_FLAT_CENTS = 2500

# Late-filing penalty daily rates (PRD 3.7)
DAILY_TAX_RATE = 0.00037
DAILY_REPORT_RATE = 0.00041

# Posture (PRD 3.13)
SUSPEND_AFTER_GRACE_DAYS = 30

# Certificates (PRD 3.10)
CERT_VALIDITY_DAYS = 90
EXPEDITED_MULTIPLIER = 1.5

# Ownership (PRD 3.11)
MAX_OWNERSHIP_BPS = 10000

# A well-formed but never-created UUID, for 404 probes.
ABSENT_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
