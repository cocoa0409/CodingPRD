"""Error classes and error-id constants (PRD §5 error catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (PRD §5 / SCAFFOLD §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"             # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                       # 404
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"                 # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 400
ERR_STALE_VENUE_VERSION = "ERR_STALE_VENUE_VERSION"   # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_ID_CHECK_NOT_PASSED = "ERR_ID_CHECK_NOT_PASSED"   # 422
ERR_LAST_CALL_NO_ALCOHOL = "ERR_LAST_CALL_NO_ALCOHOL" # 422
ERR_OVER_SERVICE_REFUSED = "ERR_OVER_SERVICE_REFUSED" # 422
ERR_RESERVATION_WINDOW = "ERR_RESERVATION_WINDOW"     # 422
ERR_TABLE_DOUBLE_BOOKED = "ERR_TABLE_DOUBLE_BOOKED"   # 409
ERR_AT_CAPACITY = "ERR_AT_CAPACITY"                   # 409
ERR_PATRON_ALREADY_INSIDE = "ERR_PATRON_ALREADY_INSIDE"  # 409
ERR_COMP_BUDGET_EXCEEDED = "ERR_COMP_BUDGET_EXCEEDED" # 422
ERR_PREAUTH_INSUFFICIENT = "ERR_PREAUTH_INSUFFICIENT" # 422
ERR_VENUE_CLOSED = "ERR_VENUE_CLOSED"                 # 409
ERR_TAB_NOT_EMPTY = "ERR_TAB_NOT_EMPTY"               # 409


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def fk_not_found(msg="Referenced foreign key does not exist in this venue"):
    return ApiError(ERR_FK_NOT_FOUND, 404, msg)


def invalid_request(msg="Malformed or invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def stale_venue_version(msg="expected_venue_version does not match current venue version"):
    return ApiError(ERR_STALE_VENUE_VERSION, 412, msg)


def invalid_state(msg="Resource not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def id_check_not_passed(msg="Admission requires an IdCheck with outcome PASS"):
    return ApiError(ERR_ID_CHECK_NOT_PASSED, 422, msg)


def last_call_no_alcohol(msg="No alcohol service during last call"):
    return ApiError(ERR_LAST_CALL_NO_ALCOHOL, 422, msg)


def over_service_refused(msg="Over-service cap reached; alcohol refused"):
    return ApiError(ERR_OVER_SERVICE_REFUSED, 422, msg)


def reservation_window(msg="Reservation window constraint violated"):
    return ApiError(ERR_RESERVATION_WINDOW, 422, msg)


def table_double_booked(msg="Table is already booked for an overlapping window"):
    return ApiError(ERR_TABLE_DOUBLE_BOOKED, 409, msg)


def at_capacity(msg="Venue is at fire-code capacity"):
    return ApiError(ERR_AT_CAPACITY, 409, msg)


def patron_already_inside(msg="Patron is already inside the venue"):
    return ApiError(ERR_PATRON_ALREADY_INSIDE, 409, msg)


def comp_budget_exceeded(msg="Promoter comp budget exceeded"):
    return ApiError(ERR_COMP_BUDGET_EXCEEDED, 422, msg)


def preauth_insufficient(msg="Pre-authorization is insufficient for the projected total"):
    return ApiError(ERR_PREAUTH_INSUFFICIENT, 422, msg)


def venue_closed(msg="Venue is closed; no child mutation permitted"):
    return ApiError(ERR_VENUE_CLOSED, 409, msg)


def tab_not_empty(msg="Cannot void a tab carrying charges; settle instead"):
    return ApiError(ERR_TAB_NOT_EMPTY, 409, msg)
