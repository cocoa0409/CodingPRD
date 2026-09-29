"""Error catalogue (PRD 5) and the ApiError exception."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_COUNTER_SCOPE_FORBIDDEN": 403,
    "ERR_SUPPLIER_SCOPE_FORBIDDEN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_COUNTER_NOT_FOUND": 404,
    "ERR_SUPPLIER_NOT_FOUND": 404,
    "ERR_SPECIES_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_CASE_LABEL_NOT_FOUND": 404,
    "ERR_AD_ITEM_NOT_FOUND": 404,
    "ERR_READING_NOT_FOUND": 404,
    "ERR_EXCURSION_NOT_FOUND": 404,
    "ERR_SAMPLE_NOT_FOUND": 404,
    "ERR_SIMP_DOCUMENT_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_SHRINK_EVENT_NOT_FOUND": 404,
    "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_LOT_VERSION": 412,
    "ERR_STALE_COUNTER_VERSION": 412,
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_LABEL_STATE_INVALID": 409,
    "ERR_CHARGEBACK_STATE_INVALID": 409,
    "ERR_CASE_LABEL_STATE_INVALID": 409,
    "ERR_AD_ITEM_STATE_INVALID": 409,
    "ERR_EXCURSION_STATE_INVALID": 409,
    "ERR_SAMPLE_STATE_INVALID": 409,
    "ERR_SIMP_STATE_INVALID": 409,
    "ERR_CERTIFICATION_STATE_INVALID": 409,
    "ERR_SHRINK_STATE_INVALID": 409,
    "ERR_VIOLATION_STATE_INVALID": 409,
    "ERR_RETEST_LIMIT_REACHED": 409,
    "ERR_COUNTER_SUSPENDED": 409,
    "ERR_COUNTER_RESTRICTED": 409,
    "ERR_OPEN_EXCURSION_BLOCKS": 409,
    "ERR_SIMP_DOCUMENT_MISSING": 409,
    "ERR_FROZEN_DISCLOSURE_CONFLICT": 422,
    "ERR_RELABEL_SPECIES_MISMATCH": 422,
    "ERR_MARKET_NAME_NOT_ACCEPTABLE": 422,
    "ERR_CLAIM_NOT_SUBSTANTIATED": 422,
    "ERR_CERTIFICATION_EXPIRED": 422,
    "ERR_SPECIES_NOT_CLAIM_ELIGIBLE": 422,
    "ERR_CASE_SLOT_OUT_OF_RANGE": 422,
    "ERR_CASE_SLOT_OCCUPIED": 409,
    "ERR_AD_WINDOW_INVALID": 422,
    "ERR_AD_WINDOW_OVERLAP": 409,
    "ERR_READING_IN_FUTURE": 422,
    "ERR_SIMP_DATE_ORDER": 422,
    "ERR_INSUFFICIENT_REMAINING_WEIGHT": 422,
    "ERR_SHRINK_EXCEEDS_REMAINING": 422,
    "ERR_CONVERSION_ALLOWANCE_EXCEEDED": 422,
    "ERR_CONVERSION_NOT_PERMITTED": 422,
    "ERR_SETTLEMENT_AMOUNT_MISMATCH": 422,
    "ERR_SUPPLIER_CREDIT_HOLD": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of the five declared roles.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this operation.",
    "ERR_COUNTER_SCOPE_FORBIDDEN": "The acting SeafoodManager does not own the addressed counter-scoped resource.",
    "ERR_SUPPLIER_SCOPE_FORBIDDEN": "The acting SupplierRep does not own the addressed supplier-scoped resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The sustainability-claim review must be decided by a different officer than the country-of-origin review.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
