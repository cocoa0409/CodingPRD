"""Error classes and error-id constants.

Every error_id and its HTTP status is taken verbatim from PRD section 5
(Error Code Catalogue) and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """An error that maps to an envelope error response.

    Carries error_id + http_status + a human-readable message, per PRD §2.2
    (Standard Error Response Format).
    """

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 / SCAFFOLD §1.6 — (error_id, http_status)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_POSITION_NOT_OFFERED = ("ERR_POSITION_NOT_OFFERED", 422)
ERR_TARGETING_MISMATCH = ("ERR_TARGETING_MISMATCH", 422)
ERR_MONETIZATION_DISABLED = ("ERR_MONETIZATION_DISABLED", 409)
ERR_NO_PRIVATE_ACCESS = ("ERR_NO_PRIVATE_ACCESS", 403)
ERR_NO_PRIVATE_FEED = ("ERR_NO_PRIVATE_FEED", 409)
ERR_MIDROLL_OVERLAP = ("ERR_MIDROLL_OVERLAP", 409)
ERR_SUBSCRIPTION_PERIOD_OVERLAP = ("ERR_SUBSCRIPTION_PERIOD_OVERLAP", 409)
ERR_NO_AVAILABLE_SLOT = ("ERR_NO_AVAILABLE_SLOT", 409)
ERR_BUDGET_WOULD_EXCEED = ("ERR_BUDGET_WOULD_EXCEED", 409)
ERR_SCHEDULE_IN_PAST = ("ERR_SCHEDULE_IN_PAST", 422)
ERR_STALE_CAMPAIGN_VERSION = ("ERR_STALE_CAMPAIGN_VERSION", 412)
ERR_CAMPAIGN_HAS_OPEN_PLACEMENTS = ("ERR_CAMPAIGN_HAS_OPEN_PLACEMENTS", 409)
ERR_SHOW_HAS_PUBLISHED_EPISODES = ("ERR_SHOW_HAS_PUBLISHED_EPISODES", 409)
ERR_NOTHING_TO_PAY = ("ERR_NOTHING_TO_PAY", 409)


def err(spec, message=None):
    """Build an ApiError from one of the (error_id, http_status) tuples above."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)
