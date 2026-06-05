"""Error classes and error-id constants for the Donor & Fundraising CRM API.

Every error_id and HTTP status here is read directly from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries error_id, message, http_status for the standard error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Auth / existence / state ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412

# --- Business rules ---
ERR_APPEAL_CAMPAIGN_MISMATCH = "ERR_APPEAL_CAMPAIGN_MISMATCH"        # 422
ERR_PLEDGE_ATTRIBUTION_MISMATCH = "ERR_PLEDGE_ATTRIBUTION_MISMATCH"  # 422
ERR_CAMPAIGN_NOT_OPEN = "ERR_CAMPAIGN_NOT_OPEN"                      # 409
ERR_DUPLICATE_EMAIL = "ERR_DUPLICATE_EMAIL"                          # 409
ERR_DUPLICATE_APPEAL_CODE = "ERR_DUPLICATE_APPEAL_CODE"              # 409
ERR_BENEFIT_EXCEEDS_GIFT = "ERR_BENEFIT_EXCEEDS_GIFT"               # 422
ERR_MATCH_PAID_BLOCKS_REFUND = "ERR_MATCH_PAID_BLOCKS_REFUND"       # 409
ERR_GIFT_INELIGIBLE_FOR_MATCH = "ERR_GIFT_INELIGIBLE_FOR_MATCH"     # 422
ERR_ZERO_DEDUCTIBLE = "ERR_ZERO_DEDUCTIBLE"                          # 422
ERR_LAPSE_WINDOW_NOT_MET = "ERR_LAPSE_WINDOW_NOT_MET"               # 409
ERR_DONOR_HAS_ACTIVE_PLEDGE = "ERR_DONOR_HAS_ACTIVE_PLEDGE"         # 409
ERR_NO_REACTIVATION_GIFT = "ERR_NO_REACTIVATION_GIFT"               # 409
ERR_PRIMARY_NOT_MEMBER = "ERR_PRIMARY_NOT_MEMBER"                   # 422
ERR_INSTALLMENT_FREQUENCY_MISMATCH = "ERR_INSTALLMENT_FREQUENCY_MISMATCH"  # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                          # 400
ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"                   # 400


def unauthenticated(msg="Missing authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation."):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Referenced entity does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Resource not in a valid state for this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Expected version does not match current version."):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_request(msg="Malformed request body."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_pagination(msg="limit must be in [1,100] and offset >= 0."):
    return ApiError(ERR_INVALID_PAGINATION, 400, msg)
