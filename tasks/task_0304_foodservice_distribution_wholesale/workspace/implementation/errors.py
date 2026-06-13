"""Error classes and error ID constants for the foodservice distribution API.

Every error_id and HTTP status here is taken verbatim from PRD §5 (Error Code
Catalogue) and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """An error that maps to the standard error envelope.

    Carries error_id, message, and http_status as defined by the PRD error
    catalogue.
    """

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (PRD §5 / SCAFFOLD §1.6) ---
ERR_MISSING_USER_CONTEXT = "ERR_MISSING_USER_CONTEXT"          # 401
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"             # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                               # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                   # 422
ERR_DUPLICATE_CODE = "ERR_DUPLICATE_CODE"                     # 409
ERR_DUPLICATE_SKU = "ERR_DUPLICATE_SKU"                       # 409
ERR_DUPLICATE_TIER = "ERR_DUPLICATE_TIER"                     # 409
ERR_CROSS_DISTRIBUTOR_REFERENCE = "ERR_CROSS_DISTRIBUTOR_REFERENCE"  # 409
ERR_SPLIT_NOT_ALLOWED = "ERR_SPLIT_NOT_ALLOWED"              # 422
ERR_EMPTY_ORDER = "ERR_EMPTY_ORDER"                          # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                      # 409
ERR_DELIVERY_DAY_MISMATCH = "ERR_DELIVERY_DAY_MISMATCH"      # 409
ERR_CUTOFF_PASSED = "ERR_CUTOFF_PASSED"                      # 409
ERR_DELIVERY_GAP_CONFLICT = "ERR_DELIVERY_GAP_CONFLICT"      # 409
ERR_LOT_EXPIRES_BEFORE_DELIVERY = "ERR_LOT_EXPIRES_BEFORE_DELIVERY"  # 409
ERR_CUSTOMER_ON_CREDIT_HOLD = "ERR_CUSTOMER_ON_CREDIT_HOLD"  # 409
ERR_CUSTOMER_CLOSED = "ERR_CUSTOMER_CLOSED"                  # 409
ERR_CUSTOMER_NOT_SETTLED = "ERR_CUSTOMER_NOT_SETTLED"        # 409
ERR_CUSTOMER_HAS_OPEN_ORDERS = "ERR_CUSTOMER_HAS_OPEN_ORDERS"  # 409
ERR_OVER_CREDIT_LIMIT = "ERR_OVER_CREDIT_LIMIT"              # 409
ERR_CREDIT_NOT_APPROVED = "ERR_CREDIT_NOT_APPROVED"          # 409
ERR_NOTHING_TO_PICK = "ERR_NOTHING_TO_PICK"                  # 409
ERR_POD_SIGNATURE_REQUIRED = "ERR_POD_SIGNATURE_REQUIRED"    # 422
ERR_ORDER_NOT_DELIVERED = "ERR_ORDER_NOT_DELIVERED"          # 409
ERR_RETURN_EXCEEDS_DELIVERED = "ERR_RETURN_EXCEEDS_DELIVERED"  # 422
ERR_STALE_CUSTOMER_VERSION = "ERR_STALE_CUSTOMER_VERSION"    # 412
ERR_VALIDATION_LIMIT = "ERR_VALIDATION_LIMIT"                # 422


# Convenience constructors -----------------------------------------------------

def missing_user_context(msg="X-User-ID and X-User-Role headers are required."):
    return ApiError(ERR_MISSING_USER_CONTEXT, 401, msg)


def forbidden_for_role(msg="The declared role is not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_FOR_ROLE, 403, msg)


def not_found(msg="The referenced resource does not exist under the distributor."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="The request body is malformed."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="The requested transition is not defined from the current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def cross_distributor(msg="A referenced resource belongs to a different distributor."):
    return ApiError(ERR_CROSS_DISTRIBUTOR_REFERENCE, 409, msg)


def validation_limit(msg="Pagination limit must be 1..100 and offset must be >= 0."):
    return ApiError(ERR_VALIDATION_LIMIT, 422, msg)
