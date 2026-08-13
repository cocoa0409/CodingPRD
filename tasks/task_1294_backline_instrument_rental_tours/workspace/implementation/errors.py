"""Error classes and error ID constants for the Backline Tour Rental API.

Every error_id / HTTP status pair is defined by SCAFFOLD.yaml §1.6 and PRD §5.
"""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (from the PRD §5 catalogue)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_UNIT_NOT_SERVICEABLE = "ERR_UNIT_NOT_SERVICEABLE"    # 422
ERR_GEAR_UNAVAILABLE = "ERR_GEAR_UNAVAILABLE"        # 409
ERR_INVALID_WINDOW = "ERR_INVALID_WINDOW"            # 422
ERR_SUBSTITUTION_NOT_ALLOWED = "ERR_SUBSTITUTION_NOT_ALLOWED"  # 422
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"      # 422
ERR_FLIGHT_CASE_REQUIRED = "ERR_FLIGHT_CASE_REQUIRED"  # 422
ERR_VENDOR_NOT_ELIGIBLE = "ERR_VENDOR_NOT_ELIGIBLE"  # 422
ERR_DEPOSIT_INSUFFICIENT = "ERR_DEPOSIT_INSUFFICIENT"  # 402
ERR_INSURANCE_REQUIRED = "ERR_INSURANCE_REQUIRED"    # 422
ERR_DUPLICATE = "ERR_DUPLICATE"                      # 409


def unauthenticated(message="Missing or malformed authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, message, 401)


def unauthorized(message="Role not permitted for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, message, 403)


def not_found(message="Resource not found"):
    return ApiError(ERR_NOT_FOUND, message, 404)


def invalid_request(message="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, message, 400)


def invalid_state(message="Current state does not permit this transition"):
    return ApiError(ERR_INVALID_STATE, message, 409)


def stale_version(message="Stale version: expected version does not match current"):
    return ApiError(ERR_STALE_VERSION, message, 412)


def segregation_of_duties(message="Claim filer may not assess their own claim"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, message, 403)


def unit_not_serviceable(message="Unit below condition or service-day floor"):
    return ApiError(ERR_UNIT_NOT_SERVICEABLE, message, 422)


def gear_unavailable(message="No unit satisfies the availability window"):
    return ApiError(ERR_GEAR_UNAVAILABLE, message, 409)


def invalid_window(message="Invalid date window"):
    return ApiError(ERR_INVALID_WINDOW, message, 422)


def substitution_not_allowed(message="Substitute model not in substitute_model_ids"):
    return ApiError(ERR_SUBSTITUTION_NOT_ALLOWED, message, 422)


def capacity_exceeded(message="Shipment capacity exceeded"):
    return ApiError(ERR_CAPACITY_EXCEEDED, message, 422)


def flight_case_required(message="Unit requires an adequate, available flight case"):
    return ApiError(ERR_FLIGHT_CASE_REQUIRED, message, 422)


def vendor_not_eligible(message="Vendor not eligible for this cross-rental"):
    return ApiError(ERR_VENDOR_NOT_ELIGIBLE, message, 422)


def deposit_insufficient(message="Artist deposit balance cannot cover the hold"):
    return ApiError(ERR_DEPOSIT_INSUFFICIENT, message, 402)


def insurance_required(message="insurance_policy_id required for non-waived artist"):
    return ApiError(ERR_INSURANCE_REQUIRED, message, 422)


def duplicate(message="Uniqueness violation"):
    return ApiError(ERR_DUPLICATE, message, 409)
