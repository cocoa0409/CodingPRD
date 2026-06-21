"""Domain error classes and the error-id catalog (SCAFFOLD §1.6 / PRD §5)."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id constants — verbatim from the scaffold error catalog (PRD §5).
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                    # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                      # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"             # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                               # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                       # 409
ERR_STALE_SHOWTIME_VERSION = "ERR_STALE_SHOWTIME_VERSION"     # 412
ERR_MATINEE_WINDOW_VIOLATION = "ERR_MATINEE_WINDOW_VIOLATION"  # 422
ERR_AUDITORIUM_DOUBLE_BOOKED = "ERR_AUDITORIUM_DOUBLE_BOOKED"  # 409
ERR_RENTAL_FEE_INVALID = "ERR_RENTAL_FEE_INVALID"            # 422
ERR_SEAT_NOT_ON_SHOWTIME = "ERR_SEAT_NOT_ON_SHOWTIME"        # 422
ERR_SEAT_UNAVAILABLE = "ERR_SEAT_UNAVAILABLE"                # 409
ERR_NO_SEATS_SELECTED = "ERR_NO_SEATS_SELECTED"              # 422
ERR_MEMBER_DOUBLE_BOOKED = "ERR_MEMBER_DOUBLE_BOOKED"        # 409
ERR_RENTAL_NO_SEAT_SALES = "ERR_RENTAL_NO_SEAT_SALES"        # 409
ERR_INSUFFICIENT_WALLET_CREDIT = "ERR_INSUFFICIENT_WALLET_CREDIT"  # 422
ERR_PAST_SHOWTIME = "ERR_PAST_SHOWTIME"                      # 409
ERR_INVALID_SPLIT_SCHEDULE = "ERR_INVALID_SPLIT_SCHEDULE"    # 422
ERR_SHOWTIME_NOT_OVER = "ERR_SHOWTIME_NOT_OVER"              # 409
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                  # 422


def unauthenticated(msg: str = "Authentication required") -> APIError:
    return APIError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg: str = "Role not permitted for this operation") -> APIError:
    return APIError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_owner(msg: str = "Not the resource owner") -> APIError:
    return APIError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg: str = "Resource not found") -> APIError:
    return APIError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg: str = "Invalid state for this transition") -> APIError:
    return APIError(ERR_INVALID_STATE, 409, msg)


def invalid_request(msg: str = "Invalid request") -> APIError:
    return APIError(ERR_INVALID_REQUEST, 422, msg)
