"""Error classes and error ID constants (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / structural
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"  # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412

# Business
ERR_ESCALATION_NOT_PERMITTED = "ERR_ESCALATION_NOT_PERMITTED"  # 409
ERR_OPEN_REVIEW_TASK = "ERR_OPEN_REVIEW_TASK"                  # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"        # 403
ERR_NOT_TASK_OWNER = "ERR_NOT_TASK_OWNER"                      # 403
ERR_CONSENT_REQUIRED = "ERR_CONSENT_REQUIRED"                  # 409
ERR_PERIOD_NOT_CLOSED = "ERR_PERIOD_NOT_CLOSED"                # 409
ERR_ACTIVITY_OUT_OF_PERIOD = "ERR_ACTIVITY_OUT_OF_PERIOD"      # 422
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"             # 409
ERR_PERIOD_OVERLAP = "ERR_PERIOD_OVERLAP"                      # 409
ERR_ACTIVE_PLAN_EXISTS = "ERR_ACTIVE_PLAN_EXISTS"             # 409
ERR_TIMELY_FILING_EXPIRED = "ERR_TIMELY_FILING_EXPIRED"        # 409
ERR_BILLING_CONSENT_GAP = "ERR_BILLING_CONSENT_GAP"           # 409
ERR_NOTHING_TO_CLAIM = "ERR_NOTHING_TO_CLAIM"                  # 409
ERR_REMITTANCE_EXCEEDS_CLAIM = "ERR_REMITTANCE_EXCEEDS_CLAIM"  # 422


def unauthenticated(msg="Missing or malformed authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation."):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Resource not found."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="A referenced resource does not exist."):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid or missing request fields."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Transition not defined from the current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Expected version does not match current version."):
    return ApiError(ERR_STALE_VERSION, 412, msg)
