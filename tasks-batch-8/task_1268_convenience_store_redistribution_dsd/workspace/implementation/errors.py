"""API error type and the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = 'ERR_UNAUTHENTICATED'            # 401
ERR_FORBIDDEN = 'ERR_FORBIDDEN'                        # 403
ERR_NOT_FOUND = 'ERR_NOT_FOUND'                        # 404
ERR_VALIDATION = 'ERR_VALIDATION'                      # 400
ERR_INVALID_STATE = 'ERR_INVALID_STATE'                # 409
ERR_MANIFEST_NOT_OPEN = 'ERR_MANIFEST_NOT_OPEN'        # 409
ERR_STALE_VERSION = 'ERR_STALE_VERSION'                # 412
ERR_TOBACCO_LICENSE_MISSING = 'ERR_TOBACCO_LICENSE_MISSING'  # 422
ERR_TAX_STAMP_UNAVAILABLE = 'ERR_TAX_STAMP_UNAVAILABLE'      # 422
ERR_ORDER_CUTOFF_PASSED = 'ERR_ORDER_CUTOFF_PASSED'    # 422
ERR_DELIVERY_WINDOW_OVERLAP = 'ERR_DELIVERY_WINDOW_OVERLAP'  # 409
ERR_PROMO_WINDOW_OVERLAP = 'ERR_PROMO_WINDOW_OVERLAP'  # 409
ERR_PRODUCT_NOT_ON_GUIDE = 'ERR_PRODUCT_NOT_ON_GUIDE'  # 422
ERR_SPLIT_CASE_NOT_ALLOWED = 'ERR_SPLIT_CASE_NOT_ALLOWED'    # 422
ERR_MANIFEST_OVERWEIGHT = 'ERR_MANIFEST_OVERWEIGHT'    # 422
ERR_MEMO_EXCEEDS_INVOICE = 'ERR_MEMO_EXCEEDS_INVOICE'  # 422
ERR_CREDIT_HOLD = 'ERR_CREDIT_HOLD'                    # 422
ERR_CREDIT_LIMIT_EXCEEDED = 'ERR_CREDIT_LIMIT_EXCEEDED'      # 422
ERR_PAYMENT_EXCEEDS_BALANCE = 'ERR_PAYMENT_EXCEEDS_BALANCE'  # 422
ERR_DUPLICATE_SKU = 'ERR_DUPLICATE_SKU'                # 409
ERR_DUPLICATE_RATE_WEEK = 'ERR_DUPLICATE_RATE_WEEK'    # 409
ERR_DUPLICATE_JURISDICTION = 'ERR_DUPLICATE_JURISDICTION'    # 409
ERR_GUIDE_DAY_MISMATCH = 'ERR_GUIDE_DAY_MISMATCH'      # 422


def unauthenticated(msg='missing or unrecognized auth headers'):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg='role not permitted for this endpoint or caller does not own the resource'):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg='referenced resource does not exist'):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def validation(msg):
    return ApiError(ERR_VALIDATION, 400, msg)


def invalid_state(msg='target resource not in a legal from-state for the requested transition'):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg='expected version does not match current resource version'):
    return ApiError(ERR_STALE_VERSION, 412, msg)
