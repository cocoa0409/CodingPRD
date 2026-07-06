"""Error classes and error ID constants for the Haunted House Attraction API.

Every error_id and HTTP status traces to PRD §5 (Error Code Catalogue) and the
scaffold §6 error table.
"""


class ApiError(Exception):
    """An application error carrying an error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth
ERR_MISSING_AUTH = "ERR_MISSING_AUTH"                         # 401
ERR_ROLE_FORBIDDEN = "ERR_ROLE_FORBIDDEN"                     # 403
ERR_NOT_OWNER = "ERR_NOT_OWNER"                               # 403
# Existence / request shape
ERR_NOT_FOUND = "ERR_NOT_FOUND"                               # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                   # 400
# State
ERR_INVALID_STATE = "ERR_INVALID_STATE"                       # 409
# Business safety
ERR_AGE_BELOW_MINIMUM = "ERR_AGE_BELOW_MINIMUM"              # 422
ERR_WAIVER_REQUIRED = "ERR_WAIVER_REQUIRED"                  # 422
ERR_SCARE_LEVEL_TOO_LOW = "ERR_SCARE_LEVEL_TOO_LOW"          # 422
ERR_ZONE_UNDERSTAFFED = "ERR_ZONE_UNDERSTAFFED"             # 409
ERR_OUTSIDE_ENTRY_WINDOW = "ERR_OUTSIDE_ENTRY_WINDOW"       # 409
ERR_OUTSIDE_SHIFT_WINDOW = "ERR_OUTSIDE_SHIFT_WINDOW"       # 409
ERR_SHIFT_OVERLAP = "ERR_SHIFT_OVERLAP"                     # 409
ERR_SLOT_OVERLAP = "ERR_SLOT_OVERLAP"                       # 409
ERR_CAPACITY_OVER_THROUGHPUT = "ERR_CAPACITY_OVER_THROUGHPUT"  # 422
ERR_SALES_BLOCKED = "ERR_SALES_BLOCKED"                     # 409
ERR_PASS_EXHAUSTED = "ERR_PASS_EXHAUSTED"                   # 409
ERR_PASS_NOT_OWNED = "ERR_PASS_NOT_OWNED"                   # 422
ERR_TICKET_VENUE_MISMATCH = "ERR_TICKET_VENUE_MISMATCH"     # 422
ERR_SLOT_CAPACITY_EXCEEDED = "ERR_SLOT_CAPACITY_EXCEEDED"   # 409
ERR_EMPTY_RESERVATION = "ERR_EMPTY_RESERVATION"             # 422
# Optimistic concurrency
ERR_STALE_TIME_SLOT_VERSION = "ERR_STALE_TIME_SLOT_VERSION"  # 412
ERR_STALE_VENUE_VERSION = "ERR_STALE_VENUE_VERSION"          # 412
ERR_STALE_ATTRACTION_VERSION = "ERR_STALE_ATTRACTION_VERSION"  # 412
ERR_STALE_WAIVER_VERSION = "ERR_STALE_WAIVER_VERSION"        # 412
