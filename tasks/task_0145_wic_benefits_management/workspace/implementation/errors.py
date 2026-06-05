"""Error classes and the WIC error catalog (PRD §5 / SCAFFOLD §1.6).

Each constant is an (error_id, http_status) tuple; `err()` builds an ApiError the
Flask error handler renders into the standard error envelope.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog: id -> HTTP status (verbatim from PRD §5) -------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_NO_INCOME_RECORDS = ("ERR_NO_INCOME_RECORDS", 409)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_DUAL_PARTICIPATION = ("ERR_DUAL_PARTICIPATION", 409)
ERR_INCOME_INELIGIBLE = ("ERR_INCOME_INELIGIBLE", 409)
ERR_RISK_INELIGIBLE = ("ERR_RISK_INELIGIBLE", 409)
ERR_CASELOAD_EXCEEDED = ("ERR_CASELOAD_EXCEEDED", 409)
ERR_CERT_NOT_ACTIVE = ("ERR_CERT_NOT_ACTIVE", 409)
ERR_EBT_FROZEN = ("ERR_EBT_FROZEN", 409)
ERR_INSUFFICIENT_BALANCE = ("ERR_INSUFFICIENT_BALANCE", 409)
ERR_VENDOR_NOT_AUTHORIZED = ("ERR_VENDOR_NOT_AUTHORIZED", 409)
ERR_CERT_PERIOD_ENDED = ("ERR_CERT_PERIOD_ENDED", 409)
ERR_APPOINTMENT_OVERLAP = ("ERR_APPOINTMENT_OVERLAP", 409)
ERR_APPOINTMENT_NOT_PAST = ("ERR_APPOINTMENT_NOT_PAST", 409)
ERR_PARTICIPANT_NOT_SERVICEABLE = ("ERR_PARTICIPANT_NOT_SERVICEABLE", 409)
ERR_CATEGORY_FOOD_MISMATCH = ("ERR_CATEGORY_FOOD_MISMATCH", 409)


def err(code_tuple, message=None):
    eid, status = code_tuple
    return ApiError(eid, status, message)
