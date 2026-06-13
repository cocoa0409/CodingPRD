"""Error classes and error ID constants for the Optometry & Vision Plan API."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (§1.6 / PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                      # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                  # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"             # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                     # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"                         # 409
ERR_WRONG_PROVIDER_ROLE = "ERR_WRONG_PROVIDER_ROLE"            # 422
ERR_PRESCRIPTION_NOT_DISPENSABLE = "ERR_PRESCRIPTION_NOT_DISPENSABLE"  # 409
ERR_REMAKE_WINDOW_CLOSED = "ERR_REMAKE_WINDOW_CLOSED"          # 409
ERR_CARRIER_MISMATCH = "ERR_CARRIER_MISMATCH"                  # 422
ERR_BENEFIT_PERIOD_CLOSED = "ERR_BENEFIT_PERIOD_CLOSED"        # 409
ERR_MEDICAL_BILLING_INELIGIBLE = "ERR_MEDICAL_BILLING_INELIGIBLE"  # 422
ERR_STALE_ELIGIBILITY_VERSION = "ERR_STALE_ELIGIBILITY_VERSION"  # 412
ERR_BENEFIT_EXHAUSTED = "ERR_BENEFIT_EXHAUSTED"                # 409
ERR_PAYMENT_EXCEEDS_BALANCE = "ERR_PAYMENT_EXCEEDS_BALANCE"    # 422


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Acting role is not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="A referenced resource does not exist"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body is invalid"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Resource is not in a legal state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def wrong_provider_role(msg="Provider role is not valid for this operation"):
    return ApiError(ERR_WRONG_PROVIDER_ROLE, 422, msg)


def prescription_not_dispensable(msg="Prescription is not dispensable"):
    return ApiError(ERR_PRESCRIPTION_NOT_DISPENSABLE, 409, msg)


def remake_window_closed(msg="Remake window is closed"):
    return ApiError(ERR_REMAKE_WINDOW_CLOSED, 409, msg)


def carrier_mismatch(msg="Carrier mismatch"):
    return ApiError(ERR_CARRIER_MISMATCH, 422, msg)


def benefit_period_closed(msg="Benefit period is closed or unavailable"):
    return ApiError(ERR_BENEFIT_PERIOD_CLOSED, 409, msg)


def medical_billing_ineligible(msg="Medical billing is not permitted for this claim"):
    return ApiError(ERR_MEDICAL_BILLING_INELIGIBLE, 422, msg)


def stale_eligibility_version(msg="Stale eligibility version"):
    return ApiError(ERR_STALE_ELIGIBILITY_VERSION, 412, msg)


def benefit_exhausted(msg="Benefit period is exhausted"):
    return ApiError(ERR_BENEFIT_EXHAUSTED, 409, msg)


def payment_exceeds_balance(msg="Payment amount is invalid"):
    return ApiError(ERR_PAYMENT_EXCEEDS_BALANCE, 422, msg)
