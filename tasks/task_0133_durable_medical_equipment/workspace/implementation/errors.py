"""Error catalog (SCAFFOLD Table 1.6 / PRD Section 5).

Every error_id and its HTTP status is taken verbatim from the spec.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http_status
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_VALUE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ACQUISITION_TYPE_MISMATCH": 422,
    "ERR_CMN_REQUIRED": 422,
    "ERR_PRIOR_AUTH_REQUIRED": 422,
    "ERR_SUPPLIER_NOT_ACCREDITED": 422,
    "ERR_NO_PROOF_OF_DELIVERY": 422,
    "ERR_POD_SIGNATURE_REQUIRED": 422,
    "ERR_CMN_SIGNED_AFTER_ORDER": 422,
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_RENTAL_CAP_REACHED": 422,
    "ERR_CYCLE_OVERLAP": 422,
    "ERR_RESUPPLY_TOO_SOON": 422,
    "ERR_NOT_A_CPAP_ORDER": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
