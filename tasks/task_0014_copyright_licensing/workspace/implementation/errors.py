"""Error catalog for the copyright-licensing API."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VERSION_MISMATCH": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_OWNERSHIP_SHARES_INVALID": 422,
    "ERR_OWNERSHIP_PROOF_MISSING": 422,
    "ERR_DUPLICATE_CO_OWNER": 409,
    "ERR_WORK_NOT_REGISTERED": 409,
    "ERR_NOT_YOUR_TURN": 409,
    "ERR_EXCLUSIVE_LICENSE_VIOLATION": 409,
    "ERR_TERRITORY_TERM_OVERLAP": 409,
    "ERR_LICENSE_NOT_ACCEPTED": 409,
    "ERR_LICENSE_NOT_EFFECTIVE": 409,
    "ERR_SIGNATURE_OUT_OF_ORDER": 409,
    "ERR_DUPLICATE_SIGNATURE": 409,
    "ERR_EFFECTIVE_DATE_OUT_OF_TERM": 422,
    "ERR_INVALID_PERIOD": 422,
    "ERR_INVALID_REVERSAL": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 409,
    "ERR_PINNED_VERSION_STALE": 409,
    "ERR_PINNED_CERTIFICATE_STALE": 409,
    "ERR_DUPLICATE_EXTERNAL_EVENT": 409,
    "ERR_EVIDENCE_MISSING": 422,
    "ERR_COMPENSATION_INVALID": 422,
    "ERR_INVALID_TERM": 422,
    "ERR_HAS_PENDING_SETTLEMENTS": 409,
    "ERR_VALIDATION": 422,
}


def api_error(error_id: str, message: str = ""):
    http = ERRORS.get(error_id, 400)
    return APIError(error_id, http, message or error_id)
