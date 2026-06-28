"""Error classes and the complete error catalog (§1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog: error_id -> http_status (PRD §5 / SCAFFOLD §1.6)
ERROR_CATALOG = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_SAMPLE_NOT_FOUND": 404,
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_ABATEMENT_ORDER_NOT_FOUND": 404,
    "ERR_MANIFEST_NOT_FOUND": 404,
    "ERR_CLEARANCE_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_WORKER_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_CROSS_PROJECT_REFERENCE": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_TIMESTAMP_IN_FUTURE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ASSESSMENT_ALREADY_CLEARED": 409,
    "ERR_ORDER_NOT_COMPLETED": 409,
    "ERR_ZONE_NOT_ACTIVE": 409,
    "ERR_CLEARANCE_IN_PROGRESS": 409,
    "ERR_ABATEMENT_IN_PROGRESS": 409,
    "ERR_NO_PASSING_CLEARANCE": 409,
    "ERR_MANIFEST_WEIGHT_SHORT": 409,
    "ERR_PROJECT_NOT_READY_FOR_BILLING": 409,
    "ERR_PROJECT_NOT_VERIFIED": 409,
    "ERR_OPEN_FINDINGS_REMAIN": 409,
    "ERR_WORKER_NOT_CERTIFIED": 422,
    "ERR_SIGNOFF_NOT_INDEPENDENT": 422,
    "ERR_CONTAINMENT_NOT_COMPLIANT": 422,
    "ERR_NESHAP_NOTICE_NOT_MET": 422,
    "ERR_TRANSPORT_PERMIT_MISSING": 422,
    "ERR_NO_CERTIFIED_CREW": 422,
    "ERR_COVERAGE_LIMIT_EXCEEDED": 402,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
