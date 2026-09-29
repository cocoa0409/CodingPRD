"""Error catalogue (PRD 5 / scaffold 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id) or readable(error_id)


# error_id -> http status
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_SEASON_NOT_FOUND": 404,
    "ERR_EPISODE_NOT_FOUND": 404,
    "ERR_CLUSTER_NOT_FOUND": 404,
    "ERR_LIVE_EVENT_NOT_FOUND": 404,
    "ERR_PLAYER_NOT_FOUND": 404,
    "ERR_CURRENCY_ACCOUNT_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_DISCLOSURE_NOT_FOUND": 404,
    "ERR_PURCHASE_NOT_FOUND": 404,
    "ERR_REFUND_REQUEST_NOT_FOUND": 404,
    "ERR_BALANCE_CHANGE_NOT_FOUND": 404,
    "ERR_COMMS_NOTICE_NOT_FOUND": 404,
    "ERR_MONITORING_RUN_NOT_FOUND": 404,
    "ERR_STALE_SEASON_VERSION": 412,
    "ERR_STALE_OFFER_VERSION": 412,
    "ERR_SEASON_INVALID_STATE": 409,
    "ERR_EPISODE_INVALID_STATE": 409,
    "ERR_CLUSTER_INVALID_STATE": 409,
    "ERR_EVENT_INVALID_STATE": 409,
    "ERR_OFFER_INVALID_APPROVAL_STATE": 409,
    "ERR_OFFER_INVALID_AVAILABILITY_STATE": 409,
    "ERR_DISCLOSURE_INVALID_STATE": 409,
    "ERR_PURCHASE_INVALID_STATE": 409,
    "ERR_REFUND_INVALID_STATE": 409,
    "ERR_BALANCE_CHANGE_INVALID_STATE": 409,
    "ERR_COMMS_NOTICE_INVALID_STATE": 409,
    "ERR_MONITORING_RUN_INVALID_STATE": 409,
    "ERR_SEASON_NOT_LIVE": 409,
    "ERR_CLUSTER_NOT_ACTIVE": 409,
    "ERR_CURRENCY_ACCOUNT_FROZEN": 409,
    "ERR_OFFER_NOT_PURCHASABLE": 409,
    "ERR_OFFER_WINDOW_CLOSED": 409,
    "ERR_GUARDIAN_VERIFICATION_REQUIRED": 422,
    "ERR_MINOR_OFFER_FORBIDDEN": 422,
    "ERR_DISCLOSURE_NOT_PUBLISHED": 422,
    "ERR_DISCLOSURE_PROBABILITY_SUM": 422,
    "ERR_FAIRNESS_FLOOR_BREACH": 422,
    "ERR_COMMS_NOTICE_REQUIRED": 422,
    "ERR_ECONOMY_INFLATED_BLOCK": 409,
    "ERR_CADENCE_DEBT_BLOCK": 409,
    "ERR_EPISODE_SEQUENCE_GAP": 422,
    "ERR_MONITORING_EPOCH_SEQUENCE": 422,
    "ERR_BALANCE_CHANGE_STAGE_SKIP": 422,
    "ERR_SEASON_WINDOW_VIOLATION": 422,
    "ERR_EPISODE_NOT_DUE": 422,
    "ERR_REFUND_WINDOW_EXPIRED": 422,
    "ERR_OFFER_SKU_WINDOW_CONFLICT": 422,
    "ERR_CURRENCY_ACCOUNT_MISSING": 422,
    "ERR_REFUND_ALREADY_REQUESTED": 409,
    "ERR_DUPLICATE_CURRENCY_ACCOUNT": 409,
    "ERR_SEASON_CODE_DUPLICATE": 409,
    "ERR_PLAYER_HANDLE_DUPLICATE": 409,
    "ERR_OFFER_SKU_DUPLICATE": 409,
    "ERR_EVENT_CODE_DUPLICATE": 409,
    "ERR_CLUSTER_CAPACITY_EXCEEDED": 422,
    "ERR_SPEND_LOCKED": 422,
    "ERR_SPEND_COOLDOWN_RESTRICTED": 422,
    "ERR_MINOR_SPEND_CAP_EXCEEDED": 422,
    "ERR_INSUFFICIENT_BALANCE": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid X-User-ID / X-User-Role headers.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting player does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "This decision may not be taken by the author of the work it governs.",
    "ERR_INVALID_REQUEST": "The request body or query string is invalid.",
}


def readable(error_id):
    """A human-readable fallback sentence for any catalogued code."""
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return words.capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, CATALOG[error_id], message)
