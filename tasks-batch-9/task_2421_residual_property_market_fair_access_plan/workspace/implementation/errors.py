"""Error catalogue for the Residual Property Fair Access Plan API.

Every error_id / http status pair here comes from PRD section 5 (Error Code
Catalogue) and SCAFFOLD 1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- the full catalogue: error_id -> http status --------------------------
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_DUPLICATE_DECLINATION": 409,
    "ERR_APPLICATION_NOT_SUBMITTABLE": 409,
    "ERR_APPLICATION_NOT_REVIEWABLE": 409,
    "ERR_INSPECTION_NOT_ORDERABLE": 409,
    "ERR_INSPECTION_ALREADY_COMPLETED": 409,
    "ERR_REQUIREMENT_STATE_INVALID": 409,
    "ERR_FILING_NOT_REVIEWABLE": 409,
    "ERR_APPLICATION_NOT_BINDABLE": 409,
    "ERR_POLICY_NOT_IN_FORCE": 409,
    "ERR_OFFER_ALREADY_OUTSTANDING": 409,
    "ERR_OFFER_NOT_OUTSTANDING": 409,
    "ERR_ASSESSMENT_STATE_INVALID": 409,
    "ERR_ALLOCATION_NOT_PAYABLE": 409,
    "ERR_PRODUCER_STATUS_INVALID": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_MAJOR_REQUIREMENT_NOT_WAIVABLE": 422,
    "ERR_ZONE_CLOSED": 409,
    "ERR_ZONE_RESTRICTED_INELIGIBLE": 409,
    "ERR_PRODUCER_NOT_APPOINTED": 409,
    "ERR_MEMBER_NOT_ACTIVE": 409,
    "ERR_NO_APPROVED_RATE": 409,
    "ERR_INSUFFICIENT_DECLINATIONS": 422,
    "ERR_PERIL_NOT_OFFERED": 422,
    "ERR_COVERAGE_LIMIT_EXCEEDED": 422,
    "ERR_VACANT_PROPERTY_INELIGIBLE": 422,
    "ERR_INSPECTION_STALE": 422,
    "ERR_BIND_DEADLINE_PASSED": 422,
    "ERR_POLICY_TERM_OVERLAP": 409,
    "ERR_FILING_WINDOW_CONFLICT": 409,
    "ERR_ELECTION_WINDOW_CLOSED": 422,
    "ERR_RATE_BELOW_VOLUNTARY_FLOOR": 422,
    "ERR_OFFER_NOT_COMPARABLE": 422,
    "ERR_ZONE_EXPOSURE_CAP_EXCEEDED": 422,
    "ERR_LOSSES_WITHIN_RESERVES": 422,
    "ERR_NO_ASSESSABLE_MEMBERS": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
}


def fail(error_id, message=None):
    """Raise the catalogued error with its catalogued HTTP status."""
    raise ApiError(error_id, CATALOG[error_id], message)


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def not_found(resource):
    raise ApiError("ERR_NOT_FOUND", 404, "%s not found" % resource)
