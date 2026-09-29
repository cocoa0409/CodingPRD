"""Error catalogue (PRD.md §5) and the ApiError exception."""

# PRD §5 — each code maps to exactly one HTTP status.
ERROR_STATUS = {
    "ERR_VALIDATION": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_CHARGEBACK_CAP_EXCEEDED": 402,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_TERMINATION_REQUIRES_COUNSEL": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_RESELLER_NOT_FOUND": 404,
    "ERR_DISTRIBUTOR_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_OBSERVATION_NOT_FOUND": 404,
    "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_EXCEPTION_NOT_FOUND": 404,
    "ERR_SERIAL_UNIT_NOT_FOUND": 404,
    "ERR_TEST_PURCHASE_NOT_FOUND": 404,
    "ERR_CHARGEBACK_NOT_FOUND": 404,
    "ERR_SERIAL_NOT_REGISTERED": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_EVALUATED": 409,
    "ERR_VIOLATION_NOT_NOTICEABLE": 409,
    "ERR_RESELLER_TERMINATED": 409,
    "ERR_TERMINATION_NOT_RESCINDABLE": 409,
    "ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION": 409,
    "ERR_POLICY_NOT_PUBLISHED": 409,
    "ERR_PRODUCT_NOT_IN_CLEARANCE": 409,
    "ERR_TEST_PURCHASE_NOT_CONFIRMED": 409,
    "ERR_SERIAL_NOT_TRACEABLE": 409,
    "ERR_EXCEPTION_WINDOW_OVERLAP": 409,
    "ERR_SUSPENSION_COOLING_OFF": 409,
    "ERR_CURE_WINDOW_EXPIRED": 409,
    "ERR_DUPLICATE_SKU": 409,
    "ERR_DUPLICATE_SERIAL": 409,
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": 409,
    "ERR_STALE_RESELLER_VERSION": 412,
    "ERR_STALE_DISTRIBUTOR_VERSION": 412,
    "ERR_ANTITRUST_PRICE_TERM_IN_AGREEMENT": 422,
    "ERR_ANTITRUST_NEGOTIATION_PROHIBITED": 422,
    "ERR_ANTITRUST_DEALER_PRICE_INPUT": 422,
    "ERR_VIOLATION_RESELLER_MISMATCH": 422,
    "ERR_DIVERSION_NOT_ATTRIBUTED": 422,
    "ERR_NON_NEGOTIATION_ACK_MISSING": 422,
    "ERR_NO_GOVERNING_POLICY": 422,
    "ERR_PRODUCT_NOT_SERIALIZED": 422,
    "ERR_OBSERVATION_STALE": 422,
    "ERR_RETROACTIVE_WINDOW_TOO_OLD": 422,
    "ERR_CHANNEL_NOT_PERMITTED": 422,
    "ERR_LADDER_RUNG_MISMATCH": 422,
    "ERR_NO_BREACH_AT_FINAL_FLOOR": 422,
    "ERR_OVERRIDE_FLOOR_OUT_OF_RANGE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return {
        "ERR_VALIDATION": "The request payload failed validation.",
        "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
        "ERR_ROLE_NOT_PERMITTED": "The acting role may not perform this operation.",
        "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own this resource.",
    }.get(error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + ".")


def fail(error_id, message=None):
    raise ApiError(error_id, message)
