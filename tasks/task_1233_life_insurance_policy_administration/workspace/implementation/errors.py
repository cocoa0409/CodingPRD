"""Error catalog and API exception type. Error IDs come from SCAFFOLD.yaml §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Error id constants (verbatim from the error catalog) -------------------
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_INSUFFICIENT_PERMISSIONS = "ERR_INSUFFICIENT_PERMISSIONS"
ERR_POLICY_NOT_FOUND = "ERR_POLICY_NOT_FOUND"
ERR_APPLICATION_NOT_FOUND = "ERR_APPLICATION_NOT_FOUND"
ERR_TEMPLATE_NOT_FOUND = "ERR_TEMPLATE_NOT_FOUND"
ERR_INSURED_NOT_FOUND = "ERR_INSURED_NOT_FOUND"
ERR_CYCLE_NOT_FOUND = "ERR_CYCLE_NOT_FOUND"
ERR_LOAN_NOT_FOUND = "ERR_LOAN_NOT_FOUND"
ERR_RIDER_NOT_FOUND = "ERR_RIDER_NOT_FOUND"
ERR_REINSTATEMENT_NOT_FOUND = "ERR_REINSTATEMENT_NOT_FOUND"
ERR_CONVERSION_NOT_FOUND = "ERR_CONVERSION_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_SEGREGATION_OF_DUTIES_VIOLATION = "ERR_SEGREGATION_OF_DUTIES_VIOLATION"
ERR_WINDOW_EXPIRED = "ERR_WINDOW_EXPIRED"
ERR_INCOMPATIBLE_REFERENCE = "ERR_INCOMPATIBLE_REFERENCE"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_CLASS_TOBACCO_MISMATCH = "ERR_CLASS_TOBACCO_MISMATCH"
ERR_INSUFFICIENT_CASH_VALUE = "ERR_INSUFFICIENT_CASH_VALUE"
ERR_INSUFFICIENT_PAYMENT = "ERR_INSUFFICIENT_PAYMENT"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_PRODUCT_NOT_PARTICIPATING = "ERR_PRODUCT_NOT_PARTICIPATING"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
ERR_NOT_FOUND = "ERR_NOT_FOUND"


def missing_context():
    return ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
                    "X-User-ID and X-User-Role headers must be present and well-formed")


def insufficient_permissions():
    return ApiError(ERR_INSUFFICIENT_PERMISSIONS, 403,
                    "Role not allowed on this endpoint")


def not_found(error_id, what):
    return ApiError(error_id, 404, "%s does not exist" % what)


def invalid_state(msg="Target resource not in a state permitting the operation"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def already_terminal(msg="Operation on a resource already in a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, 409, msg)


def segregation(msg="Segregation of duties violation"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403, msg)


def window_expired(msg="Clock-based window has passed"):
    return ApiError(ERR_WINDOW_EXPIRED, 409, msg)


def incompatible_reference(msg="Referenced entity is in an incompatible state"):
    return ApiError(ERR_INCOMPATIBLE_REFERENCE, 422, msg)


def invalid_request(msg="Field value fails schema constraint"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def class_tobacco_mismatch():
    return ApiError(ERR_CLASS_TOBACCO_MISMATCH, 422,
                    "Requested underwriting_class inconsistent with insured's tobacco_user flag")


def insufficient_cash_value(msg="Cash value insufficient for the requested operation"):
    return ApiError(ERR_INSUFFICIENT_CASH_VALUE, 402, msg)


def insufficient_payment(msg="Payment does not cover back_premium_due_cents"):
    return ApiError(ERR_INSUFFICIENT_PAYMENT, 402, msg)


def stale_version():
    return ApiError(ERR_STALE_VERSION, 412,
                    "expected_policy_version does not match current Policy.version")


def product_not_participating():
    return ApiError(ERR_PRODUCT_NOT_PARTICIPATING, 422,
                    "Dividend declaration attempted on a non-participating product")
