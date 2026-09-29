"""Error catalogue (PRD section 5 / scaffold 1.6) and the carrier exception."""

ERROR_HTTP = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_TECHNICIAN_NOT_ASSIGNED": 403,
    "ERR_SITE_OWNERSHIP_REQUIRED": 403,
    # request shape
    "ERR_INVALID_REQUEST": 422,
    # not found
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_METER_READ_NOT_FOUND": 404,
    "ERR_PERIOD_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_REMOVAL_ORDER_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_PERIOD_VERSION": 412,
    "ERR_STALE_DEVICE_VERSION": 412,
    # state machine gating
    "ERR_CONTRACT_INVALID_STATE": 409,
    "ERR_DEVICE_INVALID_STATE": 409,
    "ERR_READ_INVALID_STATE": 409,
    "ERR_PERIOD_INVALID_STATE": 409,
    "ERR_ORDER_INVALID_STATE": 409,
    "ERR_TICKET_INVALID_STATE": 409,
    "ERR_REVIEW_ALREADY_APPROVED": 409,
    "ERR_REMOVAL_INVALID_STATE": 409,
    # cross-entity state prerequisites
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_PERIOD_ALREADY_CLOSED": 409,
    "ERR_READ_NOT_NEWEST": 409,
    "ERR_DEVICE_NOT_METERABLE": 409,
    "ERR_SECURE_RELEASE_NOT_CONFIGURED": 409,
    "ERR_DEVICE_NOT_REFRESH_DUE": 409,
    "ERR_PERIOD_HAS_OPEN_EXCEPTIONS": 409,
    "ERR_SETTLEMENT_PERIOD_OPEN": 409,
    # dispatch / parts
    "ERR_TECHNICIAN_NOT_CERTIFIED": 422,
    "ERR_TECHNICIAN_REGION_MISMATCH": 422,
    "ERR_DISPATCH_WINDOW_CONFLICT": 409,
    "ERR_PART_NOT_AVAILABLE": 409,
    "ERR_PART_IS_AVAILABLE": 409,
    "ERR_LABOR_HOURS_EXCEED_LIMIT": 422,
    "ERR_SANITIZATION_EVIDENCE_MISSING": 422,
    # temporal
    "ERR_READ_OUTSIDE_PERIOD": 422,
    "ERR_READ_INTERVAL_OVERLAP": 409,
    "ERR_PERIOD_WINDOW_OVERLAP": 409,
    "ERR_PERIOD_NOT_ENDED": 409,
    "ERR_COLLECTION_NOT_DUE": 409,
    "ERR_SCHEDULE_IN_PAST": 409,
    # rate card / uniqueness / caps
    "ERR_RATE_CARD_INCOMPLETE": 409,
    "ERR_TIER_COVERAGE_GAP": 409,
    "ERR_TIER_BAND_CONFLICT": 409,
    "ERR_ASSET_TAG_DUPLICATE": 409,
    "ERR_PART_STOCK_UNDERFLOW": 409,
    "ERR_QUARTER_DUPLICATE": 409,
    "ERR_TONER_CAP_EXCEEDED": 409,
}


class ApiError(Exception):
    """Carries an error_id from the catalogue plus a human-readable message."""

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
