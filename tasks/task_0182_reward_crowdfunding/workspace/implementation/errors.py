"""Error classes and error-id constants (from PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (error_id -> http status)
ERR_MISSING_AUTH = ("ERR_MISSING_AUTH", 401)
ERR_ROLE_FORBIDDEN = ("ERR_ROLE_FORBIDDEN", 403)
ERR_NOT_OWNER = ("ERR_NOT_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_FK_INVALID = ("ERR_FK_INVALID", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_NO_TIERS = ("ERR_NO_TIERS", 409)
ERR_DEADLINE_IN_PAST = ("ERR_DEADLINE_IN_PAST", 422)
ERR_CAMPAIGN_NOT_LIVE = ("ERR_CAMPAIGN_NOT_LIVE", 409)
ERR_PLEDGE_BELOW_TIER_MIN = ("ERR_PLEDGE_BELOW_TIER_MIN", 422)
ERR_CURRENCY_MISMATCH = ("ERR_CURRENCY_MISMATCH", 422)
ERR_TIER_SOLD_OUT = ("ERR_TIER_SOLD_OUT", 409)
ERR_ADDON_SOLD_OUT = ("ERR_ADDON_SOLD_OUT", 409)
ERR_STALE_CAMPAIGN_VERSION = ("ERR_STALE_CAMPAIGN_VERSION", 412)
ERR_NOT_CLOSABLE = ("ERR_NOT_CLOSABLE", 409)
ERR_SURVEY_NOT_READY = ("ERR_SURVEY_NOT_READY", 409)
ERR_CAMPAIGN_WINDOW_OVERLAP = ("ERR_CAMPAIGN_WINDOW_OVERLAP", 409)
ERR_TIER_WINDOW_OVERLAP = ("ERR_TIER_WINDOW_OVERLAP", 409)
ERR_VALIDATION_PAGINATION = ("ERR_VALIDATION_PAGINATION", 422)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) spec tuple."""
    return ApiError(spec[0], spec[1], message)
