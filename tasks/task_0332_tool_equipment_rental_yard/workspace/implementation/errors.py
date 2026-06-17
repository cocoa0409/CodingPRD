"""Error classes and error-id constants.

Error IDs and HTTP statuses come verbatim from PRD §5 Error Code Catalogue
and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries the error_id, human message, and HTTP status for an error response."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 Error Code Catalogue
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_ACCOUNT_OWNER = "ERR_NOT_ACCOUNT_OWNER"        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_DUPLICATE_KEY = "ERR_DUPLICATE_KEY"                # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_UNIT_NOT_AVAILABLE = "ERR_UNIT_NOT_AVAILABLE"      # 409
ERR_DELIVERY_REQUIRED = "ERR_DELIVERY_REQUIRED"        # 422
ERR_UNIT_DOUBLE_BOOKED = "ERR_UNIT_DOUBLE_BOOKED"      # 409
ERR_TRUCK_DOUBLE_BOOKED = "ERR_TRUCK_DOUBLE_BOOKED"    # 409
ERR_START_IN_PAST = "ERR_START_IN_PAST"                # 422
ERR_ACCOUNT_SUSPENDED = "ERR_ACCOUNT_SUSPENDED"        # 409
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"  # 422
ERR_WRONG_FULFILLMENT = "ERR_WRONG_FULFILLMENT"        # 422
ERR_NO_UNIT_AVAILABLE = "ERR_NO_UNIT_AVAILABLE"        # 409
ERR_VALIDATION_LIMIT = "ERR_VALIDATION_LIMIT"          # 400
ERR_PAYMENT_NOT_NEGATIVE = "ERR_PAYMENT_NOT_NEGATIVE"  # 422


# Convenience constructors -------------------------------------------------

def unauthenticated(msg="Missing or malformed authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation."):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_account_owner(msg="Resource does not belong to the acting contractor."):
    return ApiError(ERR_NOT_ACCOUNT_OWNER, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def duplicate_key(msg="A resource with this key already exists."):
    return ApiError(ERR_DUPLICATE_KEY, 409, msg)


def invalid_state(msg="Resource is not in a state from which this transition is defined."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def unit_not_available(msg="The chosen equipment unit is not available."):
    return ApiError(ERR_UNIT_NOT_AVAILABLE, 409, msg)


def delivery_required(msg="This catalog item requires delivery and cannot be picked up."):
    return ApiError(ERR_DELIVERY_REQUIRED, 422, msg)


def unit_double_booked(msg="The requested rental interval overlaps an existing booking on this unit."):
    return ApiError(ERR_UNIT_DOUBLE_BOOKED, 409, msg)


def truck_double_booked(msg="The requested delivery window collides with another window on this truck."):
    return ApiError(ERR_TRUCK_DOUBLE_BOOKED, 409, msg)


def start_in_past(msg="rental_start_date is earlier than the yard clock current date."):
    return ApiError(ERR_START_IN_PAST, 422, msg)


def account_suspended(msg="The contractor account is suspended."):
    return ApiError(ERR_ACCOUNT_SUSPENDED, 409, msg)


def credit_limit_exceeded(msg="The projected balance would exceed the account credit limit."):
    return ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 422, msg)


def wrong_fulfillment(msg="The fulfillment method does not match this action."):
    return ApiError(ERR_WRONG_FULFILLMENT, 422, msg)


def no_unit_available(msg="No available unit of the catalog item is free for the interval."):
    return ApiError(ERR_NO_UNIT_AVAILABLE, 409, msg)


def validation_limit(msg="Pagination limit/offset out of bounds."):
    return ApiError(ERR_VALIDATION_LIMIT, 400, msg)


def payment_not_negative(msg="Payment amount_cents must be strictly negative."):
    return ApiError(ERR_PAYMENT_NOT_NEGATIVE, 422, msg)
