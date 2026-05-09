"""Domain constants for the Copyright Licensing API.

Numeric thresholds and well-known tokens drawn from PRD §2.8, §2.9, §3.
"""

# Ownership shares total (PRD §2.8): 10000 basis points = 100%.
TOTAL_OWNERSHIP_BPS = 10000

# Maximum revenue-share basis points (PRD §2.8): 10000 = 100%.
MAX_REVENUE_SHARE_BPS = 10000

# Reserved territory token (PRD §3.3): WORLD is exclusive of all country codes.
TERRITORY_WORLD = "WORLD"

# Allowed media types (PRD §3.3).
MEDIA_TYPES = ("DIGITAL", "PRINT", "BROADCAST", "MERCHANDISE")

# Settlement period enumeration (PRD §3.3, §3.7).
SETTLEMENT_PERIODS = ("MONTHLY", "QUARTERLY", "ANNUAL")

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
