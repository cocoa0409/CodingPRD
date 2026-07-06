"""Error catalog (PRD §5 / scaffold §1.6).

Each ApiError carries error_id, message, http_status. The error response body
uses data.error_id / data.message per the response envelope (scaffold §1.0).
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / RBAC
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)

# Existence / validation
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_VALIDATION = ("ERR_VALIDATION", 400)

# State
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)

# Screening / quota
ERR_CONSENT_REQUIRED = ("ERR_CONSENT_REQUIRED", 422)
ERR_SCREENER_AGE_FAIL = ("ERR_SCREENER_AGE_FAIL", 422)
ERR_QUOTA_CELL_FULL = ("ERR_QUOTA_CELL_FULL", 409)
ERR_DUPLICATE_SEGMENT = ("ERR_DUPLICATE_SEGMENT", 409)
ERR_RESCREEN_LIMIT = ("ERR_RESCREEN_LIMIT", 422)
ERR_STUDY_NOT_FIELDING = ("ERR_STUDY_NOT_FIELDING", 409)
ERR_SUBMIT_FIELDS_MISSING = ("ERR_SUBMIT_FIELDS_MISSING", 422)

# Focus groups
ERR_FACILITY_DOUBLE_BOOKED = ("ERR_FACILITY_DOUBLE_BOOKED", 409)
ERR_PANELIST_SCHEDULE_CONFLICT = ("ERR_PANELIST_SCHEDULE_CONFLICT", 409)
ERR_SESSION_FULL = ("ERR_SESSION_FULL", 409)
ERR_SEATS_EXCEED_CAPACITY = ("ERR_SEATS_EXCEED_CAPACITY", 422)

# Payouts
ERR_PAYOUT_BELOW_MINIMUM = ("ERR_PAYOUT_BELOW_MINIMUM", 422)
ERR_INSUFFICIENT_POINTS = ("ERR_INSUFFICIENT_POINTS", 422)

# OCC
ERR_STALE_PANELIST_VERSION = ("ERR_STALE_PANELIST_VERSION", 412)
ERR_STALE_FOCUS_GROUP_VERSION = ("ERR_STALE_FOCUS_GROUP_VERSION", 412)

# Delivery / study lifecycle
ERR_DELIVERY_NOT_READY = ("ERR_DELIVERY_NOT_READY", 409)
ERR_STUDY_NOT_CLOSED = ("ERR_STUDY_NOT_CLOSED", 409)
ERR_NO_QUOTA_CELLS = ("ERR_NO_QUOTA_CELLS", 409)
ERR_IRB_PROTOCOL_REQUIRED = ("ERR_IRB_PROTOCOL_REQUIRED", 422)


def fail(err, message=None):
    error_id, http_status = err
    raise ApiError(error_id, http_status, message)
