"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status, straight from the PRD section 5 catalogue.
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 400,
    "ERR_CONSIGNOR_NOT_FOUND": 404,
    "ERR_BUYER_NOT_FOUND": 404,
    "ERR_SCHEDULE_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_TRUCK_NOT_FOUND": 404,
    "ERR_CREW_NOT_FOUND": 404,
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_PICKUP_JOB_NOT_FOUND": 404,
    "ERR_SALE_NOT_FOUND": 404,
    "ERR_DELIVERY_ORDER_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_AUDIT_NOT_FOUND": 404,
    "ERR_STALE_CONSIGNOR_VERSION": 412,
    "ERR_STALE_ITEM_VERSION": 412,
    "ERR_ITEM_STATE_INVALID": 409,
    "ERR_ITEM_CUSTODY_INVALID": 409,
    "ERR_CONSIGNOR_ESCHEATED": 409,
    "ERR_CONSIGNOR_SUSPENDED": 409,
    "ERR_BUYER_BLOCKED": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_STATE_INVALID": 409,
    "ERR_SALE_ALREADY_REVERSED": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_CLAIM_RESUBMIT_LIMIT": 409,
    "ERR_ELECTION_ROUND_EXHAUSTED": 409,
    "ERR_PICKUP_JOB_STATE_INVALID": 409,
    "ERR_AUDIT_STATE_INVALID": 409,
    "ERR_ELECTION_DEADLINE_PASSED": 409,
    "ERR_CLAIM_WINDOW_CLOSED": 409,
    "ERR_TRUCK_WINDOW_CONFLICT": 409,
    "ERR_CREW_CAPACITY_EXCEEDED": 409,
    "ERR_WINDOW_ORDER_INVALID": 422,
    "ERR_SCHEDULE_STEP_OVERLAP": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    "ERR_PHOTOS_INSUFFICIENT": 422,
    "ERR_GRADE_REJECTED": 422,
    "ERR_LOT_NOT_READY": 409,
    "ERR_DUPLICATE_TAG_CODE": 409,
    "ERR_DISPOSITION_NOT_ELIGIBLE": 422,
    "ERR_LOT_NESTING_FORBIDDEN": 422,
    "ERR_ZONE_CLOSED": 409,
    "ERR_TRUCK_CAPACITY_EXCEEDED": 409,
    "ERR_ZONE_CAPACITY_EXCEEDED": 409,
    "ERR_AUDIT_COUNT_INVALID": 422,
    "ERR_SALE_BELOW_FLOOR": 422,
    "ERR_CLAIM_EXCEEDS_SALE": 422,
    "ERR_PAYOUT_BELOW_MINIMUM": 409,
    "ERR_INSUFFICIENT_BALANCE": 409,
    "ERR_SCHEDULE_RETIRED": 409,
    "ERR_DUPLICATE_EMAIL": 409,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of the seven declared roles.",
    "ERR_UNAUTHORIZED": "The presented role is not authorized for this endpoint or resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this operator from performing this step.",
    "ERR_VALIDATION": "The request body or query string failed schema validation.",
}


def fail(error_id, message=None):
    """Raise the catalogued error, resolving the HTTP status from the catalogue."""
    raise ApiError(error_id, CATALOG[error_id], message)
