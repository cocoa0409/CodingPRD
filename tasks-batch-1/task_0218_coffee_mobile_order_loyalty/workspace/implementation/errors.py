"""Error catalog. Error IDs and HTTP statuses come from SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID constants (verbatim from PRD §5 / SCAFFOLD §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"  # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STORE_PAUSED = "ERR_STORE_PAUSED"                # 409
ERR_SLOT_UNAVAILABLE = "ERR_SLOT_UNAVAILABLE"        # 409
ERR_SLOT_FULL = "ERR_SLOT_FULL"                      # 409
ERR_SLOT_OVERLAP = "ERR_SLOT_OVERLAP"                # 409
ERR_REWARD_NOT_APPLICABLE = "ERR_REWARD_NOT_APPLICABLE"  # 409
ERR_INSUFFICIENT_STARS = "ERR_INSUFFICIENT_STARS"    # 409
ERR_INSUFFICIENT_BALANCE = "ERR_INSUFFICIENT_BALANCE"  # 402
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_BIRTHDAY_ALREADY_CLAIMED = "ERR_BIRTHDAY_ALREADY_CLAIMED"  # 409
ERR_REFUND_NOT_ALLOWED = "ERR_REFUND_NOT_ALLOWED"    # 409
ERR_VALIDATION = "ERR_VALIDATION"                    # 422
ERR_DUPLICATE_CARD = "ERR_DUPLICATE_CARD"            # 409


# Convenience constructors
def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for the operation or ownership check failed"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="A resource id in the path does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="A FK referenced in the request body does not exist"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="Malformed request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Target resource not in a valid state for the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def store_paused(msg="Store is PAUSED and cannot accept the operation"):
    return ApiError(ERR_STORE_PAUSED, 409, msg)


def slot_unavailable(msg="Pickup slot is unavailable for the order's store / lead time"):
    return ApiError(ERR_SLOT_UNAVAILABLE, 409, msg)


def slot_full(msg="Pickup slot already holds slot_capacity reserved orders"):
    return ApiError(ERR_SLOT_FULL, 409, msg)


def slot_overlap(msg="New pickup slot's window overlaps an existing slot"):
    return ApiError(ERR_SLOT_OVERLAP, 409, msg)


def reward_not_applicable(msg="Applied reward is not applicable"):
    return ApiError(ERR_REWARD_NOT_APPLICABLE, 409, msg)


def insufficient_stars(msg="star_balance below REDEEM_STAR_COST"):
    return ApiError(ERR_INSUFFICIENT_STARS, 409, msg)


def insufficient_balance(msg="Card balance below total_cents"):
    return ApiError(ERR_INSUFFICIENT_BALANCE, 402, msg)


def stale_version(msg="OCC version mismatch"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def birthday_already_claimed(msg="Birthday reward not claimable"):
    return ApiError(ERR_BIRTHDAY_ALREADY_CLAIMED, 409, msg)


def refund_not_allowed(msg="Refund target not PAID or already PICKED_UP"):
    return ApiError(ERR_REFUND_NOT_ALLOWED, 409, msg)


def validation(msg="Pagination params out of range"):
    return ApiError(ERR_VALIDATION, 422, msg)


def duplicate_card(msg="Member already has a StoredValueCard"):
    return ApiError(ERR_DUPLICATE_CARD, 409, msg)
