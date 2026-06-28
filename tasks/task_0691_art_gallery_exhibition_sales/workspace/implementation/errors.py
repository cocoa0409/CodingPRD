"""Error catalog. error_id + HTTP status per PRD §5 / SCAFFOLD §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience constructors keyed by the canonical error ids.
def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Acting role is not permitted for this operation."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Referenced resource does not exist in scope."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Request body is malformed."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_state(msg="Resource is not in a valid state for this transition."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_version(msg="Expected version does not match the current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def artist_suspended(msg="The artist is suspended."):
    return ApiError("ERR_ARTIST_SUSPENDED", 409, msg)


def insufficient_coverage(msg="Loan coverage is less than the artwork insured value."):
    return ApiError("ERR_INSUFFICIENT_COVERAGE", 409, msg)


def schedule_conflict(msg="Requested window conflicts with an existing booking."):
    return ApiError("ERR_SCHEDULE_CONFLICT", 409, msg)


def wall_capacity_exceeded(msg="Wall capacity exceeded or position already taken."):
    return ApiError("ERR_WALL_CAPACITY_EXCEEDED", 409, msg)


def rsvp_closed(msg="RSVP is closed for this event."):
    return ApiError("ERR_RSVP_CLOSED", 409, msg)


def overpayment(msg="Payment would exceed the buyer total."):
    return ApiError("ERR_OVERPAYMENT", 409, msg)


def no_payable_balance(msg="The artist has no payable balance."):
    return ApiError("ERR_NO_PAYABLE_BALANCE", 409, msg)


def plan_sale_not_invoiced(msg="The linked sale is not in INVOICED state."):
    return ApiError("ERR_PLAN_SALE_NOT_INVOICED", 409, msg)


def lease_artwork_not_out(msg="The leased artwork is not ON_LOAN under this lease."):
    return ApiError("ERR_LEASE_ARTWORK_NOT_OUT", 409, msg)


def validation_pagination(msg="Pagination parameters out of bounds."):
    return ApiError("ERR_VALIDATION_PAGINATION", 400, msg)


def duplicate_provenance_event(msg="Provenance event must be a non-empty string."):
    return ApiError("ERR_DUPLICATE_PROVENANCE_EVENT", 409, msg)
