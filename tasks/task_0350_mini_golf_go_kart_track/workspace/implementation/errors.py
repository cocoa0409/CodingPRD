"""Error classes and error ID constants."""


class ApiError(Exception):
    """Carries error_id, message, and http_status per the scaffold error catalog."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / existence / request
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)

# State / posture / OCC
ERR_VENUE_NOT_OPEN = ("ERR_VENUE_NOT_OPEN", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_SLOT_VERSION = ("ERR_STALE_SLOT_VERSION", 412)
ERR_STALE_GROUP_VERSION = ("ERR_STALE_GROUP_VERSION", 412)

# Safety
ERR_HEIGHT_REQUIREMENT = ("ERR_HEIGHT_REQUIREMENT", 422)
ERR_WAIVER_REQUIRED = ("ERR_WAIVER_REQUIRED", 422)

# Temporal / capacity / constraint
ERR_ATTRACTION_KIND_MISMATCH = ("ERR_ATTRACTION_KIND_MISMATCH", 409)
ERR_CHECK_IN_WINDOW = ("ERR_CHECK_IN_WINDOW", 409)
ERR_NO_SHOW_WINDOW = ("ERR_NO_SHOW_WINDOW", 409)
ERR_PARTY_GROUP_EMPTY = ("ERR_PARTY_GROUP_EMPTY", 409)
ERR_SLOT_OVERLAP = ("ERR_SLOT_OVERLAP", 409)
ERR_CAPACITY_EXCEEDED = ("ERR_CAPACITY_EXCEEDED", 409)
ERR_WRISTBAND_CAP_EXCEEDED = ("ERR_WRISTBAND_CAP_EXCEEDED", 422)

# Fiscal / referential
ERR_COMBO_PASS_INVALID = ("ERR_COMBO_PASS_INVALID", 409)
ERR_INSUFFICIENT_CARD_BALANCE = ("ERR_INSUFFICIENT_CARD_BALANCE", 409)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)
