"""Error classes and the error catalogue (PRD Section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> HTTP status (PRD Section 5)
ERROR_CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_PANEL_NOT_FOUND": 404,
    "ERR_GENE_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_REQUISITION_NOT_FOUND": 404,
    "ERR_CONSENT_NOT_FOUND": 404,
    "ERR_SPECIMEN_NOT_FOUND": 404,
    "ERR_VARIANT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_PANEL_GENE_NOT_FOUND": 404,
    "ERR_SEQUENCER_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_COUNSELOR_NOT_FOUND": 404,
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_ORDER_BAD_PIPELINE_STATE": 409,
    "ERR_SPECIMEN_BAD_STATE": 409,
    "ERR_REPORT_BAD_STATE": 409,
    "ERR_BILLING_BAD_STATE": 409,
    "ERR_REFERRAL_BAD_STATE": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_PANEL_NOT_PUBLISHED": 409,
    "ERR_CONSENT_REQUIRED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VUS_REFERRAL_REQUIRED": 409,
    "ERR_UNCLASSIFIED_VARIANTS_EXIST": 409,
    "ERR_INVALID_CLASSIFICATION": 422,
    "ERR_ALLOWED_AMOUNT_INVALID": 422,
    "ERR_BILLING_NOT_CLEARED": 402,
    "ERR_COLLECT_AMOUNT_MISMATCH": 422,
    "ERR_GENE_NOT_ON_PANEL": 409,
    "ERR_RUN_WINDOW_CONFLICT": 409,
    "ERR_COUNSELOR_SLOT_CONFLICT": 409,
    "ERR_RUN_BAD_STATE": 409,
    "ERR_INVALID_REQUEST": 422,
    "ERR_NOT_FOUND": 404,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalogued HTTP status."""
    return ApiError(error_id, ERROR_CATALOG.get(error_id, 400), message)
