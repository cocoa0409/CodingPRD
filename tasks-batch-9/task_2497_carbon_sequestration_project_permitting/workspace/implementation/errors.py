"""Error catalogue (PRD Section 5) and the ApiError exception."""

ERROR_HTTP = {
    # Auth / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_TRACT_LANDOWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    # Existence
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_GEOLOGIC_MODEL_NOT_FOUND": 404,
    "ERR_WELLBORE_NOT_FOUND": 404,
    "ERR_TRACT_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_MONITORING_PLAN_NOT_FOUND": 404,
    "ERR_MONITORING_METHOD_NOT_FOUND": 404,
    "ERR_INSTRUMENT_NOT_FOUND": 404,
    "ERR_INJECTION_PERIOD_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_REMEDIATION_ORDER_NOT_FOUND": 404,
    # Posture
    "ERR_PROJECT_POSTURE_FROZEN": 409,
    # State admissibility
    "ERR_INVALID_PROJECT_STATE": 409,
    "ERR_INVALID_MODEL_STATE": 409,
    "ERR_INVALID_WELLBORE_CA_STATE": 409,
    "ERR_INVALID_TRACT_STATE": 409,
    "ERR_INVALID_PERMIT_STATE": 409,
    "ERR_INVALID_CONSTRUCTION_SEQUENCE": 409,
    "ERR_MIT_NOT_PASSED": 409,
    "ERR_INVALID_PLAN_STATE": 409,
    "ERR_INVALID_INSTRUMENT_STATE": 409,
    "ERR_INVALID_CLAIM_STATE": 409,
    # Optimistic concurrency
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_TRACT_VERSION": 412,
    "ERR_STALE_INSTRUMENT_VERSION": 412,
    # Safety / referential
    "ERR_SEAL_INTEGRITY_FAIL": 422,
    "ERR_INJECTION_PRESSURE_EXCEEDS_LIMIT": 422,
    "ERR_CASING_PROGRAM_NONCOMPLIANT": 422,
    "ERR_NON_ENDANGERMENT_NOT_DEMONSTRATED": 422,
    "ERR_MRV_PLAN_NOT_APPROVED": 422,
    "ERR_AOR_NOT_DELINEATED": 422,
    "ERR_OPEN_REMEDIATION_ORDER": 409,
    # Temporal
    "ERR_INJECTION_PERIOD_OVERLAP": 409,
    "ERR_CA_RIG_CAPACITY_EXCEEDED": 409,
    "ERR_PISC_DURATION_NOT_ELAPSED": 422,
    # Remaining business rules
    "ERR_CORRECTIVE_ACTION_INCOMPLETE": 422,
    "ERR_CA_WAIVER_NOT_ELIGIBLE": 422,
    "ERR_MRV_DOMAIN_COVERAGE_MISSING": 422,
    "ERR_MRV_COVERAGE_BELOW_MINIMUM": 422,
    "ERR_PORE_SPACE_CONSENT_INSUFFICIENT": 422,
    "ERR_UNITIZATION_CONSENT_BELOW_THRESHOLD": 422,
    "ERR_DUPLICATE_TAX_YEAR_CLAIM": 409,
    "ERR_DUPLICATE_API_NUMBER": 409,
    # Fiscal
    "ERR_ASSURANCE_INSUFFICIENT": 402,
    "ERR_ALLOCATION_EXCEEDS_FACE_AMOUNT": 422,
    # Fallback
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with an error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message if message else _default_message(error_id)
        self.http_status = http_status if http_status is not None else ERROR_HTTP.get(error_id, 400)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").lower()


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)
