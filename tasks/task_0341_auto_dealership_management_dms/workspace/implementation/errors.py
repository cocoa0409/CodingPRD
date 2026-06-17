"""Error catalog. error_id + HTTP status taken verbatim from PRD §5 / scaffold §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error id (PRD §5).
_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_VIN_DUPLICATE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VEHICLE_NOT_AVAILABLE": 409,
    "ERR_DEAL_NOT_FUNDED": 409,
    "ERR_TESTDRIVE_OVERLAP": 409,
    "ERR_BAY_OVERLAP": 409,
    "ERR_LICENSE_INVALID": 409,
    "ERR_PRODUCT_PRICE_EXCEEDS_MAX": 409,
    "ERR_MARKUP_EXCEEDS_MAX": 409,
    "ERR_LTV_EXCEEDED": 409,
    "ERR_PTI_EXCEEDED": 409,
    "ERR_LENDER_TIER_MISMATCH": 409,
    "ERR_DEAL_TYPE_NOT_FINANCE": 409,
    "ERR_CREDIT_APP_MISSING": 409,
    "ERR_STIP_MISSING": 409,
    "ERR_NO_ACTIVE_CONTRACT": 409,
    "ERR_INCENTIVE_NOT_ELIGIBLE": 409,
    "ERR_CURTAILMENT_NOT_DUE": 409,
    "ERR_TITLE_ALREADY_ACCEPTED": 409,
    "ERR_REJECTION_REASON_REQUIRED": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, _STATUS[error_id], message)
