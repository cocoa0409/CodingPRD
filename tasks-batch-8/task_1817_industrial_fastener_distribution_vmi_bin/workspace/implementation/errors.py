"""Error types and error-id constants for the VMI API."""


class ApiError(Exception):
    """Carries an error_id, human message and HTTP status through the stack."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Error id constants (PRD section 5) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_AGREEMENT_OR_SITE_RETIRED = "ERR_AGREEMENT_OR_SITE_RETIRED"  # 409
ERR_DUPLICATE = "ERR_DUPLICATE"                        # 409
ERR_NO_SUBSTITUTE = "ERR_NO_SUBSTITUTE"                # 422
ERR_ROUTE_WINDOW_OVERLAP = "ERR_ROUTE_WINDOW_OVERLAP"  # 422
ERR_STATION_WINDOW_CONFLICT = "ERR_STATION_WINDOW_CONFLICT"  # 422
ERR_CERTIFICATION_BLOCKED = "ERR_CERTIFICATION_BLOCKED"        # 422
ERR_QUANTITY_OUT_OF_BOUNDS = "ERR_QUANTITY_OUT_OF_BOUNDS"      # 422
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"      # 422
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"        # 422
ERR_ROUTE_EMPTY = "ERR_ROUTE_EMPTY"                    # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412


def unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def unauthorized(msg="Role is not permitted on this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, msg, 403)


def not_found(msg="A referenced entity does not exist"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg="Request body is malformed or fails the shape check"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def invalid_state(msg="Requested transition does not exist from the current state"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def retired(msg="Referenced site or bin agreement is RETIRED"):
    return ApiError(ERR_AGREEMENT_OR_SITE_RETIRED, msg, 409)


def duplicate(msg="Uniqueness violation"):
    return ApiError(ERR_DUPLICATE, msg, 409)


def no_substitute(msg="No eligible substitute part exists"):
    return ApiError(ERR_NO_SUBSTITUTE, msg, 422)


def route_window_overlap(msg="Route window overlaps an existing route on the site"):
    return ApiError(ERR_ROUTE_WINDOW_OVERLAP, msg, 422)


def station_conflict(msg="Station window violates closed-interval-with-buffer semantics"):
    return ApiError(ERR_STATION_WINDOW_CONFLICT, msg, 422)


def certification_blocked(msg="Critical part lacks a VALID lot certificate or agreement is BLOCKED"):
    return ApiError(ERR_CERTIFICATION_BLOCKED, msg, 422)


def quantity_bounds(msg="Count or quantity out of bounds"):
    return ApiError(ERR_QUANTITY_OUT_OF_BOUNDS, msg, 422)


def insufficient_stock(msg="Component part available_qty cannot cover the kit demand"):
    return ApiError(ERR_INSUFFICIENT_STOCK, msg, 422)


def credit_exceeded(msg="Confirmation would exceed the site credit limit"):
    return ApiError(ERR_CREDIT_LIMIT_EXCEEDED, msg, 422)


def route_empty(msg="Route has zero SUBMITTED stops or still has PENDING stops"):
    return ApiError(ERR_ROUTE_EMPTY, msg, 422)


def stale_version(msg="Expected version does not match the current entity version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)
