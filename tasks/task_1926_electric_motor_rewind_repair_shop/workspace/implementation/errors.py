class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_INSUFFICIENT_PERMISSIONS = "ERR_INSUFFICIENT_PERMISSIONS"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_INVALID_INPUT = "ERR_INVALID_INPUT"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_QUOTE_EXPIRED = "ERR_QUOTE_EXPIRED"
ERR_CUSTOMER_ON_HOLD = "ERR_CUSTOMER_ON_HOLD"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_DUPLICATE_ACTIVE = "ERR_DUPLICATE_ACTIVE"
ERR_FINAL_TEST_NOT_PASS = "ERR_FINAL_TEST_NOT_PASS"
ERR_POOL_UNAVAILABLE = "ERR_POOL_UNAVAILABLE"
ERR_WARRANTY_OUT_OF_WINDOW = "ERR_WARRANTY_OUT_OF_WINDOW"
ERR_WARRANTY_EXCLUDED_MODE = "ERR_WARRANTY_EXCLUDED_MODE"
ERR_INVOICE_HAS_PAYMENTS = "ERR_INVOICE_HAS_PAYMENTS"
ERR_CLAIMS_OPEN = "ERR_CLAIMS_OPEN"


def err_missing_headers(msg="X-User-ID or X-User-Role header missing/invalid"):
    return ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400, msg)


def err_insufficient(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_INSUFFICIENT_PERMISSIONS, 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def err_reference_not_found(msg="Body FK does not resolve"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 422, msg)


def err_invalid_state(msg="Entity not in a valid from-state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def err_invalid_input(msg="Field-level constraint violation"):
    return ApiError(ERR_INVALID_INPUT, 400, msg)


def err_stale_version(msg="expected_work_order_version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def err_quote_expired(msg="Quote has expired"):
    return ApiError(ERR_QUOTE_EXPIRED, 409, msg)


def err_customer_on_hold(msg="Customer standing is HOLD"):
    return ApiError(ERR_CUSTOMER_ON_HOLD, 402, msg)


def err_segregation(msg="Segregation of duties violation"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def err_duplicate_active(msg="Uniqueness violation"):
    return ApiError(ERR_DUPLICATE_ACTIVE, 409, msg)


def err_final_test_not_pass(msg="Release requires latest FINAL verdict PASS and any CORE_LOSS verdict PASS"):
    return ApiError(ERR_FINAL_TEST_NOT_PASS, 409, msg)


def err_pool_unavailable(msg="Pool checkout blocked"):
    return ApiError(ERR_POOL_UNAVAILABLE, 409, msg)


def err_warranty_out_of_window(msg="Claim is out of warranty window"):
    return ApiError(ERR_WARRANTY_OUT_OF_WINDOW, 422, msg)


def err_warranty_excluded_mode(msg="Failure mode is excluded from warranty coverage"):
    return ApiError(ERR_WARRANTY_EXCLUDED_MODE, 422, msg)


def err_invoice_has_payments(msg="Void requires amount_paid_cents == 0"):
    return ApiError(ERR_INVOICE_HAS_PAYMENTS, 409, msg)


def err_claims_open(msg="Close blocked by open warranty claim or unreturned pool loan"):
    return ApiError(ERR_CLAIMS_OPEN, 409, msg)
