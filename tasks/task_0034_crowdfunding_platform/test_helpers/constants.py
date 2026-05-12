"""Domain thresholds — numeric constants from PRD prose.

Every literal corresponds to a numeric threshold, default, or magic constant
named in PRD §2 / §3 prose. The reference implementation is expected to use
these same literal values.
"""

# Pagination — PRD §2.3
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Order modification window — PRD §3.4
# ("computed as the earlier of two moments: the project's deadline, and the
#  order's created_at plus 72 hours")
ORDER_MODIFICATION_WINDOW_HOURS = 72

# Submit deadline gate — PRD §3.3 (and §2.8)
# ("deadline must be more than 24 hours after the current time")
SUBMIT_DEADLINE_MIN_HOURS = 24

# Title length — PRD §3.2 ("title (4 to 120 characters)")
TITLE_MIN_LENGTH = 4
TITLE_MAX_LENGTH = 120

# Media URI count — PRD §3.2 ("between 1 and 10 image or video URIs")
MEDIA_URIS_MIN_COUNT = 1
MEDIA_URIS_MAX_COUNT = 10

# Charge attempt cap — PRD §3.6
# ("transitions the order to CHARGE_FAILED only when charge_attempts is at
#  least 3")
CHARGE_ATTEMPT_CAP = 3

# Update silence threshold — PRD §3.9
# ("a silence of exactly 30 days is compliant; a silence strictly greater
#  than 30 days is non-compliant")
MAX_SILENCE_DAYS = 30

# Commission basis points by category — PRD §3.10
COMMISSION_RATE_BPS_BY_CATEGORY = {
    "TECH": 500,       # 5.00%
    "ART": 700,        # 7.00%
    "COMMUNITY": 300,  # 3.00%
}

# Channel fee — PRD §3.10
CHANNEL_FEE_BPS = 290        # 2.90%
CHANNEL_FEE_FLOOR_CENTS = 30  # minimum 30 cents

# Tax withholding — PRD §3.12
# ("backup withholding at 2,400 basis points (24%)")
BACKUP_WITHHOLDING_BPS = 2400
# ("computed at 1,000 basis points (10%) of the taxable base")
STANDARD_WITHHOLDING_BPS = 1000
# ("if the taxable base in cents is strictly greater than 60,000")
TAX_REPORTING_THRESHOLD_CENTS = 60000

# Basis-points denominator
BPS_DENOMINATOR = 10000


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "ORDER_MODIFICATION_WINDOW_HOURS",
    "SUBMIT_DEADLINE_MIN_HOURS",
    "TITLE_MIN_LENGTH",
    "TITLE_MAX_LENGTH",
    "MEDIA_URIS_MIN_COUNT",
    "MEDIA_URIS_MAX_COUNT",
    "CHARGE_ATTEMPT_CAP",
    "MAX_SILENCE_DAYS",
    "COMMISSION_RATE_BPS_BY_CATEGORY",
    "CHANNEL_FEE_BPS",
    "CHANNEL_FEE_FLOOR_CENTS",
    "BACKUP_WITHHOLDING_BPS",
    "STANDARD_WITHHOLDING_BPS",
    "TAX_REPORTING_THRESHOLD_CENTS",
    "BPS_DENOMINATOR",
]
