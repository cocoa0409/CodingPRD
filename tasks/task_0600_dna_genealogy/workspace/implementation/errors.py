"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = HTTP_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


HTTP_STATUS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_SUBSCRIPTION_LOCKED": 402,
    "ERR_INSUFFICIENT_CREDIT": 402,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_CONSENT_REQUIRED": 403,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_KIT_NOT_FOUND": 404,
    "ERR_SAMPLE_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_INSTRUMENT_NOT_FOUND": 404,
    "ERR_CONSENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_MATCH_NOT_FOUND": 404,
    "ERR_TREE_NOT_FOUND": 404,
    "ERR_PERSON_NOT_FOUND": 404,
    "ERR_HINT_NOT_FOUND": 404,
    "ERR_DATA_REQUEST_NOT_FOUND": 404,
    "ERR_CUSTOMER_PURGED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_BARCODE_ALREADY_ACTIVATED": 409,
    "ERR_DNA_NOT_READY": 409,
    "ERR_EXTRACTION_ATTEMPTS_EXHAUSTED": 409,
    "ERR_CONSENT_OVERLAP": 409,
    "ERR_CONSENT_COOLING_OFF": 409,
    "ERR_SAMPLE_NOT_READY": 409,
    "ERR_INSTRUMENT_OFFLINE": 409,
    "ERR_BATCH_WINDOW_OVERLAP": 409,
    "ERR_PENDING_DATA_REQUEST": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_BARCODE_MISMATCH": 422,
    "ERR_EMPTY_BATCH": 422,
    "ERR_TREE_CYCLE": 422,
    "ERR_TREE_PERSON_LIMIT": 422,
}

DEFAULT_MESSAGE = {
    "ERR_INVALID_REQUEST": "The request payload is not well-formed.",
    "ERR_UNAUTHENTICATED": "Missing or unrecognized authentication headers.",
    "ERR_SUBSCRIPTION_LOCKED": "The owning subscription does not permit this operation.",
    "ERR_INSUFFICIENT_CREDIT": "Store credit is insufficient for the computed charge.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The resource belongs to a different customer.",
    "ERR_CONSENT_REQUIRED": "A live consent grant is required for this capability.",
    "ERR_CUSTOMER_PURGED": "The customer account has been purged.",
    "ERR_INVALID_STATE": "The requested transition is not declared from the current state.",
    "ERR_BARCODE_ALREADY_ACTIVATED": "The kit has already been activated.",
    "ERR_DNA_NOT_READY": "The customer has no genotyped sample.",
    "ERR_EXTRACTION_ATTEMPTS_EXHAUSTED": "All extraction attempts have been consumed.",
    "ERR_CONSENT_OVERLAP": "The consent window overlaps an existing active grant.",
    "ERR_CONSENT_COOLING_OFF": "The consent cooling-off buffer has not elapsed.",
    "ERR_SAMPLE_NOT_READY": "The sample is not ready for batching.",
    "ERR_INSTRUMENT_OFFLINE": "The instrument is in maintenance.",
    "ERR_BATCH_WINDOW_OVERLAP": "The run window conflicts with an existing batch.",
    "ERR_PENDING_DATA_REQUEST": "The customer already has an open data request.",
    "ERR_STALE_VERSION": "The supplied version does not match the current version.",
    "ERR_BARCODE_MISMATCH": "The submitted barcode does not match the kit.",
    "ERR_EMPTY_BATCH": "The batch has no member samples.",
    "ERR_TREE_CYCLE": "The parent link is invalid or would create a cycle.",
    "ERR_TREE_PERSON_LIMIT": "The subscription tier's family-tree person limit would be exceeded.",
}
