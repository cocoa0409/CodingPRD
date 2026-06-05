"""Error classes and error ID constants (PRD §5, SCAFFOLD §1.6)."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Auth
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"           # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                 # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403

# Existence / structural
ERR_NOT_FOUND = "ERR_NOT_FOUND"                       # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 400

# State / OCC
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412

# Temporal windows
ERR_WINDOW_CLOSED = "ERR_WINDOW_CLOSED"               # 422
ERR_CURE_DEADLINE_PASSED = "ERR_CURE_DEADLINE_PASSED"  # 422
ERR_VOTING_NOT_OPEN = "ERR_VOTING_NOT_OPEN"           # 422

# Business constraints
ERR_NOT_CITIZEN = "ERR_NOT_CITIZEN"                   # 422
ERR_UNDERAGE = "ERR_UNDERAGE"                         # 422
ERR_NO_PRECINCT_MATCH = "ERR_NO_PRECINCT_MATCH"       # 422
ERR_DUPLICATE_REGISTRATION = "ERR_DUPLICATE_REGISTRATION"  # 409
ERR_PRECINCT_FULL = "ERR_PRECINCT_FULL"               # 409
ERR_ALREADY_VOTED = "ERR_ALREADY_VOTED"               # 409
ERR_REGISTRATION_NOT_ACTIVE = "ERR_REGISTRATION_NOT_ACTIVE"  # 409
ERR_BALLOT_NOT_CURED = "ERR_BALLOT_NOT_CURED"         # 409
ERR_BALLOT_BLOCKS_WITHDRAW = "ERR_BALLOT_BLOCKS_WITHDRAW"  # 409
ERR_PRECINCT_NOT_TALLIED = "ERR_PRECINCT_NOT_TALLIED"  # 409
ERR_PRECINCTS_NOT_TALLIED = "ERR_PRECINCTS_NOT_TALLIED"  # 409
ERR_RECOUNT_IN_PROGRESS = "ERR_RECOUNT_IN_PROGRESS"   # 409
ERR_BACKUP_IN_USE = "ERR_BACKUP_IN_USE"               # 409


# Helper constructors -------------------------------------------------
def unauthenticated(msg: str = "Missing or malformed X-User-ID / X-User-Role header.") -> APIError:
    return APIError(ERR_UNAUTHENTICATED, msg, 401)


def unauthorized(msg: str = "Role is not authorized for this endpoint.") -> APIError:
    return APIError(ERR_UNAUTHORIZED, msg, 403)


def segregation(msg: str = "Acting user conflicts with a prior step (separation of duties).") -> APIError:
    return APIError(ERR_SEGREGATION_OF_DUTIES, msg, 403)


def not_found(msg: str = "Resource not found.") -> APIError:
    return APIError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg: str = "Malformed or missing request fields.") -> APIError:
    return APIError(ERR_INVALID_REQUEST, msg, 400)


def invalid_state(msg: str = "Resource is not in a state that permits this transition.") -> APIError:
    return APIError(ERR_INVALID_STATE, msg, 409)


def stale_version(msg: str = "Stale parent version.") -> APIError:
    return APIError(ERR_STALE_VERSION, msg, 412)
