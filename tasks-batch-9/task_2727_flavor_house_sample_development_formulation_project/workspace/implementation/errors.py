"""Error catalogue (§1.6 / PRD §5) - 61 error ids with their HTTP statuses."""

ERROR_HTTP = {
    # authentication / authorization / confidentiality
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_IP_TIER_FORBIDDEN": 403,
    "ERR_DISCLOSURE_GRANT_EXPIRED": 403,
    "ERR_REDACTION_LEVEL_INSUFFICIENT": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_CODE": 409,
    # existence
    "ERR_BRIEF_NOT_FOUND": 404,
    "ERR_MATERIAL_NOT_FOUND": 404,
    "ERR_SUBSTANTIATION_NOT_FOUND": 404,
    "ERR_FORMULA_NOT_FOUND": 404,
    "ERR_COMPONENT_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_CABINET_NOT_FOUND": 404,
    "ERR_RETENTION_NOT_FOUND": 404,
    "ERR_RIG_NOT_FOUND": 404,
    "ERR_TEST_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_FORECAST_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    # own-state preconditions
    "ERR_BRIEF_STATE_INVALID": 409,
    "ERR_SUBSTANTIATION_STATE_INVALID": 409,
    "ERR_FORMULA_STATE_INVALID": 409,
    "ERR_FORMULA_NOT_REVISABLE": 409,
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_RETENTION_STATE_INVALID": 409,
    "ERR_TEST_STATE_INVALID": 409,
    "ERR_SHIPMENT_STATE_INVALID": 409,
    "ERR_BATCH_STATE_INVALID": 409,
    # cross-entity state preconditions
    "ERR_BRIEF_NOT_ACCEPTED": 409,
    "ERR_FORMULA_NOT_APPROVED": 409,
    "ERR_SUB_FORMULA_NOT_COSTED": 409,
    "ERR_LOT_NOT_QC_PASSED": 409,
    "ERR_LOT_NOT_RELEASED": 409,
    # concurrency and version pinning
    "ERR_STALE_FORMULA_VERSION": 412,
    "ERR_STALE_BRIEF_VERSION": 412,
    "ERR_PINNED_FORMULA_STALE": 409,
    # safety, compliance, regulatory
    "ERR_ALLERGEN_EXCLUSION_BREACH": 422,
    "ERR_CLAIM_UNSUBSTANTIATED": 422,
    "ERR_MAX_USE_EXCEEDED": 422,
    "ERR_SUBSTANTIATION_REVOKED": 422,
    # graph and capacity constraints
    "ERR_FORMULA_CYCLE": 422,
    "ERR_FORMULA_NO_COMPONENTS": 422,
    "ERR_WEIGHT_SUM_INVALID": 422,
    "ERR_CABINET_CAPACITY_EXCEEDED": 422,
    # temporal
    "ERR_INVALID_INTERVAL": 422,
    "ERR_RETENTION_PERIOD_TOO_SHORT": 422,
    "ERR_RIG_WINDOW_CONFLICT": 409,
    "ERR_PACKET_EXPIRED": 422,
    # referential coherence
    "ERR_COMPONENT_TYPE_MISMATCH": 422,
    "ERR_DOC_PACKET_INCOMPLETE": 422,
    "ERR_PINNED_DOC_STALE": 422,
    "ERR_RIG_MATRIX_MISMATCH": 422,
    "ERR_DOSAGE_MISMATCH": 422,
    "ERR_GRANT_FORMULA_MISMATCH": 422,
    "ERR_PARENT_FORMULA_MISMATCH": 422,
    # fiscal
    "ERR_INSUFFICIENT_SAMPLE_MASS": 422,
    "ERR_COST_IN_USE_CAP_EXCEEDED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def invalid(message="request is not valid"):
    raise ApiError("ERR_INVALID_REQUEST", message)
