"""Error classes and error-id constants for the Title Insurance Escrow API.

Error catalog and HTTP statuses are taken verbatim from PRD §5 / scaffold §1.6.
"""


class ApiError(Exception):
    """An application error carrying the scaffold's error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (PRD §5 / scaffold §1.6) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                      # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                  # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                      # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"                          # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                          # 409
ERR_INVALID_GAP_WINDOW = "ERR_INVALID_GAP_WINDOW"               # 422
ERR_NO_ISSUED_COMMITMENT = "ERR_NO_ISSUED_COMMITMENT"           # 409
ERR_CHAIN_NOT_VERIFIED = "ERR_CHAIN_NOT_VERIFIED"               # 409
ERR_EXCEPTIONS_OPEN = "ERR_EXCEPTIONS_OPEN"                      # 409
ERR_NO_ISSUED_POLICY = "ERR_NO_ISSUED_POLICY"                   # 409
ERR_COMMITMENT_NOT_ISSUED = "ERR_COMMITMENT_NOT_ISSUED"         # 409
ERR_COVERAGE_EXCEEDS_COMMITMENT = "ERR_COVERAGE_EXCEEDS_COMMITMENT"  # 409
ERR_COMMITMENT_NOT_EXPIRABLE = "ERR_COMMITMENT_NOT_EXPIRABLE"   # 409
ERR_GAP_DEFECT = "ERR_GAP_DEFECT"                               # 409
ERR_POLICY_NOT_ISSUED = "ERR_POLICY_NOT_ISSUED"                 # 409
ERR_POLICY_HAS_OPEN_CLAIM = "ERR_POLICY_HAS_OPEN_CLAIM"         # 409
ERR_CURATIVE_REQUIRED = "ERR_CURATIVE_REQUIRED"                 # 409
ERR_NO_RESOLVED_CURATIVE = "ERR_NO_RESOLVED_CURATIVE"           # 409
ERR_ORDER_NOT_DISBURSABLE = "ERR_ORDER_NOT_DISBURSABLE"         # 409
ERR_INSUFFICIENT_ESCROW = "ERR_INSUFFICIENT_ESCROW"            # 409
ERR_WIRE_WINDOW_OVERLAP = "ERR_WIRE_WINDOW_OVERLAP"           # 409
ERR_ESCROW_WOULD_GO_NEGATIVE = "ERR_ESCROW_WOULD_GO_NEGATIVE"  # 409
ERR_ESCROW_NOT_ZERO = "ERR_ESCROW_NOT_ZERO"                    # 409


# Convenience constructors that pin the HTTP status from the catalog.
def unauthenticated(msg="Missing or unrecognized role/identity"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def stale_version(msg="expected_order_version does not match the order's current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_state(msg="Resource is not in the required state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)
