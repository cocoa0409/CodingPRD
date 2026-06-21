"""Error catalog and the ApiError exception type.

Every error_id and HTTP status is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> HTTP status (PRD §5 / SCAFFOLD §1.6).
ERROR_STATUS = {
    # --- auth ---
    "ERR_MISSING_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    # --- request validation ---
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_NIGHT_WINDOW": 422,
    "ERR_PAGINATION_INVALID": 422,
    # --- not found ---
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_BED_NOT_FOUND": 404,
    "ERR_STUDY_NOT_FOUND": 404,
    "ERR_SCORING_REPORT_NOT_FOUND": 404,
    "ERR_DME_NOT_FOUND": 404,
    "ERR_COMPLIANCE_NOT_FOUND": 404,
    "ERR_FOLLOWUP_NOT_FOUND": 404,
    # --- state ---
    "ERR_INVALID_STATE": 409,
    "ERR_AUTH_NOT_REQUIRED": 409,
    "ERR_STUDY_NOT_CANCELLABLE": 409,
    "ERR_DME_NOT_CANCELLABLE": 409,
    "ERR_REFERRAL_HAS_ACTIVE_STUDY": 409,
    # --- cross-entity / referential ---
    "ERR_REFERRAL_NOT_AUTHORIZED": 409,
    "ERR_STUDY_NOT_INTERPRETED": 409,
    "ERR_RESUPPLY_PREDECESSOR_INVALID": 409,
    # --- temporal / scheduling ---
    "ERR_AUTH_EXPIRED": 409,
    "ERR_BED_DOUBLE_BOOKED": 409,
    "ERR_BED_OUT_OF_SERVICE": 409,
    "ERR_COMPLIANCE_WINDOW_OVERLAP": 409,
    # --- modality / clinical ---
    "ERR_BED_REQUIRED": 422,
    "ERR_HSAT_BED_NOT_ALLOWED": 422,
    "ERR_INSUFFICIENT_RECORDING": 422,
    "ERR_TITRATION_PRESSURE_REQUIRED": 422,
    "ERR_CPAP_NOT_RECOMMENDED": 409,
    # --- concurrency (OCC) ---
    "ERR_STALE_REFERRAL_VERSION": 412,
    "ERR_STALE_STUDY_VERSION": 412,
    "ERR_STALE_DME_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
