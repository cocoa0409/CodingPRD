"""Error catalog. error_id + http_status pairs straight from PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog: error_id -> http status
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_UNIT_NON_COMPLIANT": 409,
    "ERR_WARRANTY_LAPSED": 409,
    "ERR_TECH_NOT_QUALIFIED": 409,
    "ERR_MODEL_UNDERSIZED": 409,
    "ERR_FUEL_INADEQUATE": 409,
    "ERR_DUPLICATE_SERIAL": 409,
    "ERR_SEGREGATION_VIOLATION": 409,
    "ERR_TECH_OVERLOADED": 409,
    "ERR_NO_ASSESSMENT": 409,
    "ERR_PERMIT_NOT_APPROVED": 409,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_DUPLICATE_LICENSE": 409,
    "ERR_DUPLICATE_SKU": 409,
    "ERR_DUPLICATE_RECALL_CODE": 409,
    "ERR_MODEL_INACTIVE": 409,
    "ERR_REMEDIATION_OVERDUE": 409,
    "ERR_CAMPAIGN_HAS_OPEN_REMEDIATIONS": 409,
    "ERR_DISPATCH_IN_PROGRESS": 409,
    "ERR_NOT_ASSIGNED_TECH": 403,
    "ERR_TECH_DOUBLE_BOOKED": 409,
    "ERR_UNIT_VISIT_COLLISION": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, CATALOG[error_id], message)
