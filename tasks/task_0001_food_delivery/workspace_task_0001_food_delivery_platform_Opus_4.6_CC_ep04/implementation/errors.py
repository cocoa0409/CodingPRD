class ApiError(Exception):
    def __init__(self, error_id, message, status_code):
        self.error_id = error_id
        self.message = message
        self.status_code = status_code
        super().__init__(message)


ERR_AUTH_REQUIRED = ("ERR_AUTH_REQUIRED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_VERSION_CONFLICT = ("ERR_VERSION_CONFLICT", 409)
ERR_ORDER_ALREADY_ASSIGNED = ("ERR_ORDER_ALREADY_ASSIGNED", 409)
ERR_DUPLICATE_RETURN = ("ERR_DUPLICATE_RETURN", 409)
ERR_RESTAURANT_UNAVAILABLE = ("ERR_RESTAURANT_UNAVAILABLE", 422)
ERR_SUSPEND_CRITERIA_NOT_MET = ("ERR_SUSPEND_CRITERIA_NOT_MET", 422)
ERR_RETURN_WINDOW_EXPIRED = ("ERR_RETURN_WINDOW_EXPIRED", 422)
ERR_REFUND_AMOUNT_INVALID = ("ERR_REFUND_AMOUNT_INVALID", 422)
ERR_ORDER_INVALID = ("ERR_ORDER_INVALID", 422)
ERR_RELATED_RETURN_UNRESOLVED = ("ERR_RELATED_RETURN_UNRESOLVED", 422)
ERR_VALIDATION = ("ERR_VALIDATION", 422)


def raise_error(err_tuple, message=""):
    error_id, status_code = err_tuple
    if not message:
        message = error_id
    raise ApiError(error_id, message, status_code)
