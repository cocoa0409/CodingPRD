"""Domain error classes and error-id constants (PRD §5 error catalogue)."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---- error_id constants (exact strings from PRD §5 / SCAFFOLD §1.6) ----------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"               # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                           # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"         # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                           # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"       # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"               # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"                   # 409
ERR_EPCS_REQUIREMENTS_NOT_MET = "ERR_EPCS_REQUIREMENTS_NOT_MET"   # 422
ERR_VACCINE_INTERVAL_VIOLATION = "ERR_VACCINE_INTERVAL_VIOLATION" # 409
ERR_SLOT_OVERLAP = "ERR_SLOT_OVERLAP"                     # 409
ERR_NO_PCP_BOUND = "ERR_NO_PCP_BOUND"                     # 409
ERR_PANEL_AT_CAPACITY = "ERR_PANEL_AT_CAPACITY"           # 409
ERR_REFERRAL_EXPIRED = "ERR_REFERRAL_EXPIRED"             # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                   # 412
ERR_PATIENT_HAS_OPEN_VISITS = "ERR_PATIENT_HAS_OPEN_VISITS"       # 409
ERR_DUPLICATE_PORTAL_ACCOUNT = "ERR_DUPLICATE_PORTAL_ACCOUNT"     # 409
ERR_DUPLICATE_NPI = "ERR_DUPLICATE_NPI"                   # 409
ERR_DUPLICATE_CPT_CODE = "ERR_DUPLICATE_CPT_CODE"         # 409
