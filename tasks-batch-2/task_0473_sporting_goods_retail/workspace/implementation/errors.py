"""Error classes and error-id constants for the Sporting Goods Retail API.

Error catalog mirrors PRD §5 / scaffold §1.6 exactly (ids and HTTP statuses).
"""


class ApiError(Exception):
    """An application error carrying the scaffold's error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (PRD §5 / scaffold §1.6) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                  # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"          # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                            # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"               # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"                   # 409
ERR_EMBROIDERY_NOT_ALLOWED = "ERR_EMBROIDERY_NOT_ALLOWED"  # 422
ERR_FITMENT_REQUIRED = "ERR_FITMENT_REQUIRED"             # 422
ERR_LICENSE_REQUIRED = "ERR_LICENSE_REQUIRED"             # 422
ERR_INVALID_JURISDICTION = "ERR_INVALID_JURISDICTION"     # 422
ERR_INVALID_MARKDOWN_WINDOW = "ERR_INVALID_MARKDOWN_WINDOW"  # 422
ERR_MARKDOWN_OVERLAP = "ERR_MARKDOWN_OVERLAP"             # 409
ERR_PRICE_MATCH_NOT_LOWER = "ERR_PRICE_MATCH_NOT_LOWER"   # 422
ERR_ORDER_NOT_MATCHABLE = "ERR_ORDER_NOT_MATCHABLE"       # 409
ERR_INSUFFICIENT_INVENTORY = "ERR_INSUFFICIENT_INVENTORY"  # 409
ERR_STALE_ORDER_VERSION = "ERR_STALE_ORDER_VERSION"       # 412
ERR_STALE_INVENTORY_VERSION = "ERR_STALE_INVENTORY_VERSION"  # 412
ERR_DUPLICATE_INVENTORY_ROW = "ERR_DUPLICATE_INVENTORY_ROW"  # 409
ERR_DUPLICATE_EMAIL = "ERR_DUPLICATE_EMAIL"               # 409
ERR_VALIDATION_PAGINATION = "ERR_VALIDATION_PAGINATION"   # 422


# Convenience constructors that pin the HTTP status from the catalog.
def unauthenticated(msg="Missing or unrecognized X-User-ID / X-User-Role header"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="Acting customer is not the owner of this resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Malformed or invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Resource is not in a state from which this transition is defined"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def pagination(msg="limit/offset outside allowed bounds"):
    return ApiError(ERR_VALIDATION_PAGINATION, 422, msg)
