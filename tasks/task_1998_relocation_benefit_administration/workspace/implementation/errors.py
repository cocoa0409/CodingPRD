"""Error classes and error ID constants, read from SCAFFOLD.yaml errors catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"        # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_POLICY_NOT_FOUND = "ERR_POLICY_NOT_FOUND"        # 422
ERR_EMPLOYEE_NOT_ACTIVE = "ERR_EMPLOYEE_NOT_ACTIVE"  # 409
ERR_EMPLOYEE_NOT_TERMINATED = "ERR_EMPLOYEE_NOT_TERMINATED"  # 409
ERR_VENDOR_SUSPENDED = "ERR_VENDOR_SUSPENDED"        # 409
ERR_CASE_NOT_OPEN = "ERR_CASE_NOT_OPEN"              # 409
ERR_INVALID_DATES = "ERR_INVALID_DATES"              # 422
ERR_HOUSING_OVERLAP = "ERR_HOUSING_OVERLAP"          # 409
ERR_SURVEY_CONFLICT = "ERR_SURVEY_CONFLICT"          # 409
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"    # 409
ERR_CAP_EXCEEDED = "ERR_CAP_EXCEEDED"                # 409
ERR_NIGHTS_LIMIT_EXCEEDED = "ERR_NIGHTS_LIMIT_EXCEEDED"  # 409
ERR_HOME_SALE_NOT_ELIGIBLE = "ERR_HOME_SALE_NOT_ELIGIBLE"  # 409
ERR_PAYMENT_EXCEEDS_BALANCE = "ERR_PAYMENT_EXCEEDS_BALANCE"  # 422
ERR_APPEAL_LIMIT_REACHED = "ERR_APPEAL_LIMIT_REACHED"  # 409


def err_unauthenticated(msg="Authentication required"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def err_forbidden(msg="Forbidden"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def err_invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def err_not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def err_invalid_state(msg="Invalid state"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def err_already_terminal(msg="Resource is in a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, msg, 409)


def err_stale_version(msg="Stale case version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def err_policy_not_found(msg="No matching policy tier"):
    return ApiError(ERR_POLICY_NOT_FOUND, msg, 422)


def err_employee_not_active(msg="Employee is not ACTIVE"):
    return ApiError(ERR_EMPLOYEE_NOT_ACTIVE, msg, 409)


def err_employee_not_terminated(msg="Employee is not TERMINATED"):
    return ApiError(ERR_EMPLOYEE_NOT_TERMINATED, msg, 409)


def err_vendor_suspended(msg="Vendor is SUSPENDED"):
    return ApiError(ERR_VENDOR_SUSPENDED, msg, 409)


def err_case_not_open(msg="Case is not IN_PROGRESS"):
    return ApiError(ERR_CASE_NOT_OPEN, msg, 409)


def err_invalid_dates(msg="Invalid dates"):
    return ApiError(ERR_INVALID_DATES, msg, 422)


def err_housing_overlap(msg="TEMP_HOUSING booking overlaps an existing booking"):
    return ApiError(ERR_HOUSING_OVERLAP, msg, 409)


def err_survey_conflict(msg="Vendor survey conflict within 2 hours"):
    return ApiError(ERR_SURVEY_CONFLICT, msg, 409)


def err_duplicate_resource(msg="Duplicate resource"):
    return ApiError(ERR_DUPLICATE_RESOURCE, msg, 409)


def err_cap_exceeded(msg="Component cap exceeded"):
    return ApiError(ERR_CAP_EXCEEDED, msg, 409)


def err_nights_limit(msg="Nights limit exceeded"):
    return ApiError(ERR_NIGHTS_LIMIT_EXCEEDED, msg, 409)


def err_home_sale_not_eligible(msg="Policy is not home-sale eligible"):
    return ApiError(ERR_HOME_SALE_NOT_ELIGIBLE, msg, 409)


def err_payment_exceeds_balance(msg="Payment exceeds balance"):
    return ApiError(ERR_PAYMENT_EXCEEDS_BALANCE, msg, 422)


def err_appeal_limit(msg="Appeal limit reached"):
    return ApiError(ERR_APPEAL_LIMIT_REACHED, msg, 409)
