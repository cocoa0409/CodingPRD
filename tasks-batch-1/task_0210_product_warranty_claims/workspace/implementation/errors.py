"""Domain error classes and the error-id catalog (PRD §5)."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog — exact ids/statuses from SCAFFOLD §1.6 / PRD §5.
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"        # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                    # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"            # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"            # 412
ERR_NOT_OWNER = "ERR_NOT_OWNER"                    # 403
ERR_DEFECT_NOT_COVERED = "ERR_DEFECT_NOT_COVERED"  # 422
ERR_WARRANTY_EXPIRED = "ERR_WARRANTY_EXPIRED"      # 422
ERR_REFUND_NOT_ELIGIBLE = "ERR_REFUND_NOT_ELIGIBLE"  # 422
ERR_TIER_MISMATCH = "ERR_TIER_MISMATCH"            # 422
ERR_DUPLICATE_SERIAL = "ERR_DUPLICATE_SERIAL"      # 409
ERR_COVERAGE_EXHAUSTED = "ERR_COVERAGE_EXHAUSTED"  # 422
ERR_COVERAGE_OVERLAP = "ERR_COVERAGE_OVERLAP"      # 409
ERR_CLAIM_COOLDOWN = "ERR_CLAIM_COOLDOWN"          # 409
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"        # 400


def unauth(msg: str = "Authentication required"):
    raise APIError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg: str = "Role not permitted for this operation"):
    raise APIError(ERR_FORBIDDEN, 403, msg)


def not_found(what: str = "resource"):
    raise APIError(ERR_NOT_FOUND, 404, f"{what} not found")


def invalid_state(msg: str = "Invalid state for this transition"):
    raise APIError(ERR_INVALID_STATE, 409, msg)


def not_owner(msg: str = "Caller does not own this resource"):
    raise APIError(ERR_NOT_OWNER, 403, msg)


def invalid_request(msg: str = "Invalid request"):
    raise APIError(ERR_INVALID_REQUEST, 400, msg)
