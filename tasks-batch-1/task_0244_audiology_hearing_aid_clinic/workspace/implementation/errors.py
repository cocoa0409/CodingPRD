"""Error catalogue and the ApiError exception used throughout the app.

Every error_id / http_status pair here is taken verbatim from PRD §5 and
SCAFFOLD §1.6. Nothing is invented.
"""


class ApiError(Exception):
    """A domain error carrying the machine-readable error_id, an HTTP status,
    and a human-readable message that surface in the error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / structural
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_DUPLICATE_MODEL_CODE = "ERR_DUPLICATE_MODEL_CODE"  # 409

# Business
ERR_EVALUATION_PATIENT_MISMATCH = "ERR_EVALUATION_PATIENT_MISMATCH"  # 422
ERR_NOT_A_CANDIDATE = "ERR_NOT_A_CANDIDATE"          # 422
ERR_DEVICE_NOT_INDICATED = "ERR_DEVICE_NOT_INDICATED"  # 422
ERR_TRIAL_EXPIRED = "ERR_TRIAL_EXPIRED"              # 422
ERR_BENEFIT_EXPIRED = "ERR_BENEFIT_EXPIRED"          # 422
ERR_BENEFIT_INACTIVE = "ERR_BENEFIT_INACTIVE"        # 422
ERR_RETURN_WINDOW_CLOSED = "ERR_RETURN_WINDOW_CLOSED"  # 422
ERR_TRIAL_NOT_CLOSED = "ERR_TRIAL_NOT_CLOSED"        # 422
ERR_OUTSIDE_WARRANTY_WINDOW = "ERR_OUTSIDE_WARRANTY_WINDOW"  # 422
ERR_CYCLE_NOT_DUE = "ERR_CYCLE_NOT_DUE"              # 422
ERR_FIRMWARE_MISMATCH = "ERR_FIRMWARE_MISMATCH"      # 422
ERR_RECALL_NOT_REMEDIATED = "ERR_RECALL_NOT_REMEDIATED"  # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_VALIDATION_LIMIT = "ERR_VALIDATION_LIMIT"        # 422


def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Caller is not permitted to perform this operation."):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body is malformed."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Transition is not defined from the resource's current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Provided version does not match the current resource version."):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def validation_limit(msg="Pagination parameters are out of range."):
    return ApiError(ERR_VALIDATION_LIMIT, 422, msg)
