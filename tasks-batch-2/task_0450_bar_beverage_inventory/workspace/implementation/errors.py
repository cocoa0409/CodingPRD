"""Error catalog and the ApiError exception.

Every error_id / http_status pair is read verbatim from SCAFFOLD.yaml §1.6
and PRD §5. Never assume an error ID — these are the exact strings.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (PRD §5 / SCAFFOLD §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_PRODUCT_NOT_ON_PO = "ERR_PRODUCT_NOT_ON_PO"       # 422
ERR_RECIPE_NOT_PUBLISHED = "ERR_RECIPE_NOT_PUBLISHED" # 422
ERR_WEIGHT_BELOW_TARE = "ERR_WEIGHT_BELOW_TARE"       # 422
ERR_NOT_A_KEG = "ERR_NOT_A_KEG"                       # 422
ERR_INVALID_PAR = "ERR_INVALID_PAR"                   # 422
ERR_DUPLICATE_SKU = "ERR_DUPLICATE_SKU"               # 409
ERR_DUPLICATE_COUNT_LINE = "ERR_DUPLICATE_COUNT_LINE" # 409
ERR_NO_ACTIVE_PAR = "ERR_NO_ACTIVE_PAR"               # 422
ERR_EMPTY_MENU = "ERR_EMPTY_MENU"                     # 422
ERR_SHORT_RECEIPT = "ERR_SHORT_RECEIPT"               # 422
ERR_COUNT_WINDOW_OVERLAP = "ERR_COUNT_WINDOW_OVERLAP" # 422
ERR_LINE_OVERLAP = "ERR_LINE_OVERLAP"                 # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 400
ERR_VALIDATION = "ERR_VALIDATION"                     # 422


def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="The acting role is not permitted to perform this operation."):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Target resource is not in a state allowing this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="expected_count_session_version does not match the session version."):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_request(msg="Request body failed schema validation."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def validation(msg="Business-rule violation."):
    return ApiError(ERR_VALIDATION, 422, msg)
