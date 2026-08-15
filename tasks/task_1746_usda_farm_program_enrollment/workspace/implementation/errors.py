"""Error classes and error ID constants for the FSA API."""


class ApiError(Exception):
    """Exception carrying error_id, message, and HTTP status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (from SCAFFOLD.yaml §1.6 / PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_FARM_VERSION = "ERR_STALE_FARM_VERSION"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_ACREAGE_DEADLINE_PASSED = "ERR_ACREAGE_DEADLINE_PASSED"
ERR_ELECTION_WINDOW_CLOSED = "ERR_ELECTION_WINDOW_CLOSED"
ERR_CONSERVATION_NOT_CERTIFIED = "ERR_CONSERVATION_NOT_CERTIFIED"
ERR_AGI_INELIGIBLE = "ERR_AGI_INELIGIBLE"
ERR_NO_ACTIVE_ELECTION = "ERR_NO_ACTIVE_ELECTION"
ERR_ACREAGE_NOT_CERTIFIED = "ERR_ACREAGE_NOT_CERTIFIED"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_CROPLAND_EXCEEDED = "ERR_CROPLAND_EXCEEDED"
ERR_SHARE_SUM_INVALID = "ERR_SHARE_SUM_INVALID"
ERR_BASE_ACRE_IMBALANCE = "ERR_BASE_ACRE_IMBALANCE"
ERR_LOSS_THRESHOLD_NOT_MET = "ERR_LOSS_THRESHOLD_NOT_MET"
ERR_PAYMENT_LIMITATION_EXCEEDED = "ERR_PAYMENT_LIMITATION_EXCEEDED"
ERR_LINE_ACRES_EXCEED_FIELD = "ERR_LINE_ACRES_EXCEED_FIELD"
ERR_YIELD_UPDATE_WINDOW_CLOSED = "ERR_YIELD_UPDATE_WINDOW_CLOSED"


def unauthenticated(message="Missing or malformed X-User-Role / X-User-ID"):
    return ApiError(ERR_UNAUTHENTICATED, message, 401)


def unauthorized(message="Role lacks permission for the endpoint"):
    return ApiError(ERR_UNAUTHORIZED, message, 403)


def not_found(message="Path id or FK reference does not resolve"):
    return ApiError(ERR_NOT_FOUND, message, 404)


def invalid_state(message="Target resource not in a state allowing the transition"):
    return ApiError(ERR_INVALID_STATE, message, 409)


def stale_farm_version(message="expected_farm_version does not match current Farm.version"):
    return ApiError(ERR_STALE_FARM_VERSION, message, 412)


def invalid_request(message="Missing required field, invalid enum, or malformed value"):
    return ApiError(ERR_INVALID_REQUEST, message, 400)
