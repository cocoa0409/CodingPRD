"""Error classes and error ID -> HTTP status mapping (from PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENTIAL_MISMATCH": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_COMPLIANCE_GATE_FAILED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_RX_EXPIRED": 422,
    "ERR_RX_NOT_SIGNED": 422,
    "ERR_PHYSICIAN_NOT_PECOS": 422,
    "ERR_KX_WITHOUT_AUTH": 422,
    "ERR_DUPLICATE_MILESTONE": 409,
    "ERR_REPLACEMENT_IN_WARRANTY": 422,
    "ERR_INVALID_BILLING_AMOUNT": 422,
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_STALE_AUTH_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    "ERR_MILESTONE_REQUIRED": 422,
    "ERR_SUPPLIER_NOT_ACCREDITED": 422,
    "ERR_NOT_DELIVERED": 422,
    "ERR_INVALID_APPEAL_OUTCOME": 400,
    "ERR_SAME_SIMILAR_OVERLAP": 422,
    "ERR_AUTH_ALREADY_OPEN": 409,
}
