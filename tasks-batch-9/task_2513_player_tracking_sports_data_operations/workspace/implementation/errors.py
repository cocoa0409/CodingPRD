"""Error taxonomy for the Player Tracking Data Ops API.

Every identifier and HTTP status here is transcribed from PRD.md §5 (Error Code
Catalogue) and cross-checked against SCAFFOLD.yaml §1.6.
"""

ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_INSTALLATION_NOT_FOUND": 404,
    "ERR_CLUB_NOT_FOUND": 404,
    "ERR_PLAYER_NOT_FOUND": 404,
    "ERR_CONSENT_RECORD_NOT_FOUND": 404,
    "ERR_GAME_NOT_FOUND": 404,
    "ERR_EVENT_TAG_NOT_FOUND": 404,
    "ERR_CORRECTION_REQUEST_NOT_FOUND": 404,
    "ERR_RIGHTS_WINDOW_NOT_FOUND": 404,
    "ERR_LICENSEE_NOT_FOUND": 404,
    "ERR_FEED_SESSION_NOT_FOUND": 404,
    "ERR_STALE_GAME_VERSION": 412,
    "ERR_INVALID_INSTALLATION_STATE": 409,
    "ERR_GAME_NOT_COLLECTING": 409,
    "ERR_GAME_NOT_COLLECTED": 409,
    "ERR_INVALID_GAME_COLLECTION_STATE": 409,
    "ERR_GAME_ALREADY_OFFICIAL": 409,
    "ERR_INVALID_TAG_STATE": 409,
    "ERR_CORRECTION_ALREADY_RESOLVED": 409,
    "ERR_INVALID_CONSENT_STATE": 409,
    "ERR_RIGHTS_WINDOW_REVOKED": 409,
    "ERR_SESSION_NOT_ACTIVE": 409,
    "ERR_VENUE_NOT_CERTIFIED": 409,
    "ERR_BIOMETRIC_CONSENT_MISSING": 422,
    "ERR_BIOMETRIC_SCOPE_NOT_LICENSED": 422,
    "ERR_CBA_VERSION_MISMATCH": 422,
    "ERR_CONSENT_EXPIRY_IN_PAST": 422,
    "ERR_CALIBRATION_NOT_PASSING": 409,
    "ERR_CALIBRATION_EXPIRED": 422,
    "ERR_INVALID_WINDOW_BOUNDS": 422,
    "ERR_SESSION_WINDOW_OUTSIDE_RIGHTS": 422,
    "ERR_RIGHTS_WINDOW_OVERLAP": 409,
    "ERR_CONSENT_ALREADY_PENDING": 409,
    "ERR_SCOPE_NOT_IN_TIER": 422,
    "ERR_SCOPE_NOT_IN_RIGHTS_WINDOW": 422,
    "ERR_LATENCY_BELOW_VENUE_FLOOR": 422,
    "ERR_LATENCY_SLA_UNSATISFIABLE": 422,
    "ERR_VENUE_TRANSPORT_CAPACITY_EXCEEDED": 409,
    "ERR_OPEN_CORRECTIONS": 409,
    "ERR_NO_ACCEPTED_TAGS": 422,
    "ERR_QUALITY_INDEX_BELOW_THRESHOLD": 422,
    "ERR_NORMALIZATION_SEGMENTS_EMPTY": 422,
    "ERR_RIGHTS_WINDOW_GAME_MISMATCH": 409,
    "ERR_PLAYER_NOT_IN_GAME": 409,
    "ERR_RIGHTS_HOLDER_MISMATCH": 409,
    "ERR_ALLOCATION_POOL_EXHAUSTED": 409,
    "ERR_LICENSEE_QUOTA_EXHAUSTED": 402,
    "ERR_SESSION_RESERVATION_EXCEEDED": 402,
}


class ApiError(Exception):
    """Raised anywhere in the request path; rendered by the Flask error handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."


def raise_error(error_id, message=None):
    raise ApiError(error_id, message)


def invalid_request(message="Request body failed schema validation."):
    raise ApiError("ERR_INVALID_REQUEST", message)
