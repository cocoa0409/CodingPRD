"""Error classes and error ID constants (from SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"            # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"    # 403
# Existence
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
# State
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
# Business
ERR_CONTROLLED_SUBSTANCE_BLOCKED = "ERR_CONTROLLED_SUBSTANCE_BLOCKED"  # 422
ERR_PHARMACY_MISMATCH = "ERR_PHARMACY_MISMATCH"      # 422
ERR_COPAY_DRUG_MISMATCH = "ERR_COPAY_DRUG_MISMATCH"  # 422
ERR_COPAY_ALREADY_LINKED = "ERR_COPAY_ALREADY_LINKED"  # 409
ERR_PRICE_ORDER_VIOLATION = "ERR_PRICE_ORDER_VIOLATION"  # 422
ERR_QUOTE_PERIOD_OVERLAP = "ERR_QUOTE_PERIOD_OVERLAP"  # 409
ERR_MEMBERSHIP_PERIOD_OVERLAP = "ERR_MEMBERSHIP_PERIOD_OVERLAP"  # 409
ERR_COVERAGE_LIMIT = "ERR_COVERAGE_LIMIT"            # 422
ERR_NOT_MAIL_ORDER_PHARMACY = "ERR_NOT_MAIL_ORDER_PHARMACY"  # 422
ERR_NO_INSURANCE_ON_FILE = "ERR_NO_INSURANCE_ON_FILE"  # 422
ERR_COMPARISON_NOT_RESOLVED = "ERR_COMPARISON_NOT_RESOLVED"  # 409
ERR_QUANTITY_OUT_OF_RANGE = "ERR_QUANTITY_OUT_OF_RANGE"  # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_VALIDATION = "ERR_VALIDATION"                    # 422
ERR_PAGINATION_INVALID = "ERR_PAGINATION_INVALID"    # 400


def unauthenticated(msg=None):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg or "Missing or unknown authentication headers.")


def forbidden_role(msg=None):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg or "Role not permitted for this operation.")


def not_resource_owner(msg=None):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg or "Caller does not own this resource.")


def not_found(msg=None):
    return ApiError(ERR_NOT_FOUND, 404, msg or "Resource not found.")


def invalid_state(msg=None):
    return ApiError(ERR_INVALID_STATE, 409, msg or "Requested transition not defined from current state.")


def stale_version(msg=None):
    return ApiError(ERR_STALE_VERSION, 412, msg or "Stale version on optimistic concurrency check.")


def invalid_request(msg=None):
    return ApiError(ERR_INVALID_REQUEST, 400, msg or "Missing required field, wrong type, or invalid enum value.")


def validation(msg=None):
    return ApiError(ERR_VALIDATION, 422, msg or "Business-rule violation.")


def pagination_invalid(msg=None):
    return ApiError(ERR_PAGINATION_INVALID, 400, msg or "limit/offset outside allowed bounds.")
