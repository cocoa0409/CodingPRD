"""API error type carrying the scaffold error-catalog identifiers.

Every error id and HTTP status below is taken verbatim from SCAFFOLD.yaml
§1.6 / PRD §5. Raise `err(ERROR_ID, message)` anywhere in a request handler.
"""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


ERROR_STATUSES = {
    # auth (400/403)
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INVALID_REQUEST": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CLIENT_SCOPE_VIOLATION": 403,
    "ERR_NOT_ASSIGNED_INSPECTOR": 403,
    "ERR_SEGREGATION_OF_DUTIES_VERIFICATION": 403,
    "ERR_SEGREGATION_OF_DUTIES_ISSUANCE": 403,
    "ERR_CLIENT_HIGH_RISK": 403,
    # existence (404)
    "ERR_NOT_FOUND": 404,
    # concurrency (412)
    "ERR_STALE_CLIENT_VERSION": 412,
    # state (409)
    "ERR_CLIENT_INVALID_STATE": 409,
    "ERR_FACILITY_INVALID_STATE": 409,
    "ERR_INGREDIENT_INVALID_STATE": 409,
    "ERR_PRODUCT_INVALID_STATE": 409,
    "ERR_PRODUCT_INGREDIENT_INVALID_STATE": 409,
    "ERR_VISIT_INVALID_STATE": 409,
    "ERR_FINDING_INVALID_STATE": 409,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    "ERR_INVOICE_INVALID_STATE": 409,
    "ERR_CERTIFICATE_INVALID_STATE": 409,
    "ERR_CERTIFICATE_PRODUCT_INVALID_STATE": 409,
    "ERR_WINDOW_INVALID_STATE": 409,
    "ERR_EQUIPMENT_LINE_INVALID_STATE": 409,
    # business_safety
    "ERR_ANIMAL_SOURCE_DOCUMENTATION_REQUIRED": 422,
    "ERR_INITIAL_VISIT_REQUIRED": 409,
    "ERR_OPEN_MAJOR_FINDINGS": 409,
    "ERR_EQUIPMENT_UNASSESSED": 409,
    "ERR_FACILITY_NOT_APPROVED": 409,
    "ERR_PRODUCT_NOT_CERTIFIABLE": 409,
    "ERR_NO_COVERING_CERTIFICATE": 409,
    # business_referential
    "ERR_CROSS_CLIENT_REFERENCE": 422,
    "ERR_INGREDIENT_NOT_APPROVED": 409,
    "ERR_PRODUCT_ALREADY_CERTIFIED": 409,
    "ERR_DUPLICATE_PRODUCT_INGREDIENT": 409,
    "ERR_SCHEME_MISMATCH": 422,
    "ERR_NO_ACTIVE_AGREEMENT": 409,
    # business_temporal (409)
    "ERR_VISIT_WINDOW_NOT_ACTIVE": 409,
    "ERR_RENEWAL_WINDOW_CLOSED": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_INSPECTOR_SCHEDULE_CONFLICT": 409,
    "ERR_SUPERVISOR_WINDOW_CONFLICT": 409,
    # business_constraint
    "ERR_ACTIVE_AGREEMENT_EXISTS": 409,
    "ERR_RENEWAL_ALREADY_EXISTS": 409,
    "ERR_CERTIFICATE_SCOPE_EMPTY": 422,
    "ERR_PRODUCT_HAS_NO_INGREDIENTS": 422,
    "ERR_WINDOW_REFERENCED_BY_CERTIFICATE": 409,
    "ERR_CERTIFICATE_NOT_RENEWABLE": 409,
    "ERR_DUPLICATE_ANNUAL_INVOICE": 409,
    # business_fiscal (402)
    "ERR_CERTIFICATION_FEE_UNPAID": 402,
    # defensive fallback (never raised by spec logic)
    "ERR_INTERNAL": 500,
}


def err(error_id, message):
    """Raise an ApiError with the catalog-pinned HTTP status."""
    raise ApiError(error_id, ERROR_STATUSES[error_id], message)
