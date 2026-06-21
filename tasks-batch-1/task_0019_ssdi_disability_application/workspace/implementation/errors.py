"""Error catalog and exception class."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status). Messages are dynamic per call.
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_APPLICATION_STATE = "ERR_INVALID_APPLICATION_STATE"
ERR_INVALID_HEARING_STATE = "ERR_INVALID_HEARING_STATE"
ERR_CDR_NOT_DUE = "ERR_CDR_NOT_DUE"
ERR_STALE_APPLICATION_VERSION = "ERR_STALE_APPLICATION_VERSION"
ERR_STALE_AWARD_VERSION = "ERR_STALE_AWARD_VERSION"
ERR_EOD_BEFORE_AOD = "ERR_EOD_BEFORE_AOD"
ERR_LISTING_REFERENCE_REQUIRED = "ERR_LISTING_REFERENCE_REQUIRED"
ERR_HEARING_LEAD_TIME = "ERR_HEARING_LEAD_TIME"
ERR_RECONSIDERATION_WINDOW_EXPIRED = "ERR_RECONSIDERATION_WINDOW_EXPIRED"
ERR_CHILD_OVER_AGE = "ERR_CHILD_OVER_AGE"
ERR_FAMILY_MAX_EXCEEDED = "ERR_FAMILY_MAX_EXCEEDED"
ERR_SSI_NOT_REQUESTED = "ERR_SSI_NOT_REQUESTED"
ERR_DUPLICATE_CREDIT_YEAR = "ERR_DUPLICATE_CREDIT_YEAR"
ERR_INVALID_STATE_CODE = "ERR_INVALID_STATE_CODE"
ERR_EVIDENCE_REQUIRED = "ERR_EVIDENCE_REQUIRED"


def unauthenticated(msg="missing X-User-ID or X-User-Role header"):
    return APIError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="role not permitted for this endpoint"):
    return APIError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="resource not found"):
    return APIError(ERR_NOT_FOUND, 404, msg)


def ref_not_found(msg="referenced resource does not exist"):
    return APIError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="invalid request payload"):
    return APIError(ERR_INVALID_REQUEST, 400, msg)
