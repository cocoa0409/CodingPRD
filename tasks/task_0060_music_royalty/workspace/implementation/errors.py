"""Error catalog and exception class."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog of error_id -> http_status
ERROR_CATALOG = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_WORK_FROZEN": 409,
    "ERR_POOL_HAS_FROZEN_DISTRIBUTIONS": 409,
    "ERR_DISTRIBUTION_NOT_FORFEITABLE": 409,
    "ERR_MINOR_REQUIRES_GUARDIAN": 422,
    "ERR_MINOR_PAYOUT_BLOCKED": 422,
    "ERR_PLAYBACK_SIGNATURE_INVALID": 403,
    "ERR_PLAYBACK_RANGE_INVALID": 422,
    "ERR_DUPLICATE_BATCH": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_COCREATOR_SUM_INVALID": 422,
    "ERR_SHARE_SUM_INVALID": 422,
    "ERR_AGENCY_BINDING_INAPPLICABLE": 422,
    "ERR_AGENCY_BINDING_OVERLAP": 409,
    "ERR_RULE_WEIGHTS_INVALID": 422,
    "ERR_RULE_NOT_EFFECTIVE": 422,
    "ERR_BELOW_MIN_PAYOUT": 422,
    "ERR_DUPLICATE_CYCLE": 409,
    "ERR_RESOLUTION_INVALID": 422,
}


def raise_err(error_id: str, message: str = ""):
    http_status = ERROR_CATALOG.get(error_id, 422)
    raise APIError(error_id, http_status, message or error_id)
