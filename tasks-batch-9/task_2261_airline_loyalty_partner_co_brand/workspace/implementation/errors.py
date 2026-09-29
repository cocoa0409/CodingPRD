"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""

ERROR_STATUS = {
    # auth / schema
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_MEMBER_SCOPE_VIOLATION": 403,
    "ERR_ISSUER_SCOPE_VIOLATION": 403,
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_ISSUER_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_PROMOTION_NOT_FOUND": 404,
    "ERR_AWARD_WINDOW_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_PARTNER_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_FRAUD_CASE_NOT_FOUND": 404,
    "ERR_POSTING_NOT_FOUND": 404,
    # state / concurrency / governance
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_MEMBER_FROZEN": 409,
    "ERR_PERIOD_LOCKED": 409,
    # temporal
    "ERR_INVALID_INTERVAL": 422,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_INVALID_NOTICE_SCHEDULE": 422,
    "ERR_INVALID_TERM": 422,
    "ERR_TRAVEL_DATE_OUT_OF_WINDOW": 422,
    "ERR_HOLD_EXPIRED": 409,
    # constraint / integrity
    "ERR_PROMOTION_WINDOW_OVERLAP": 409,
    "ERR_AWARD_WINDOW_BUFFER_VIOLATION": 409,
    "ERR_AGREEMENT_TERM_OVERLAP": 409,
    "ERR_SUPERSEDE_TARGET_INVALID": 422,
    "ERR_PROMOTION_CHANNEL_MISMATCH": 422,
    "ERR_RECIPROCITY_SUSPENDED": 409,
    "ERR_CROSS_PROGRAM_REFERENCE": 422,
    # capacity
    "ERR_AWARD_WINDOW_CLOSED": 409,
    "ERR_SEAT_COUNT_INVALID": 422,
    "ERR_AWARD_SEATS_UNAVAILABLE": 409,
    "ERR_SAVER_ALLOTMENT_EXHAUSTED": 409,
    # fiscal
    "ERR_INSUFFICIENT_MILES": 402,
    "ERR_VOLUME_COMMITMENT_EXCEEDED": 409,
    "ERR_ISSUER_SUSPENDED": 409,
    "ERR_ISSUER_CAP_EXCEEDED": 409,
    # governance / accounting
    "ERR_REACTION_RISK_EXCEEDED": 409,
    "ERR_PERIOD_ALREADY_POSTED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
