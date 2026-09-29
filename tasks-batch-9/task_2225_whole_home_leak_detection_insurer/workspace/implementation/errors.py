"""Error catalogue (PRD section 5).  Each entry maps an error_id to its HTTP
status code; ApiError carries the pair through to the envelope.
"""

ERROR_STATUS = {
    # ---- auth ----
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # ---- existence ----
    "ERR_HOMEOWNER_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_ANOMALY_EVENT_NOT_FOUND": 404,
    "ERR_ESCALATION_TICKET_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_ATTESTATION_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    # ---- request shape ----
    "ERR_INVALID_REQUEST": 400,
    # ---- concurrency ----
    "ERR_STALE_DEVICE_VERSION": 412,
    "ERR_STALE_PROPERTY_VERSION": 412,
    # ---- uniqueness ----
    "ERR_DEVICE_SERIAL_TAKEN": 409,
    "ERR_POLICY_NUMBER_TAKEN": 409,
    "ERR_CONTACT_RANK_TAKEN": 409,
    # ---- state ----
    "ERR_HOMEOWNER_DEACTIVATED": 409,
    "ERR_INSTALL_ALREADY_VERIFIED": 409,
    "ERR_DEVICE_NOT_ACCEPTING_TELEMETRY": 409,
    "ERR_VALVE_ALREADY_IN_STATE": 409,
    "ERR_EVENT_NOT_ACTIONABLE": 409,
    "ERR_TICKET_NOT_PENDING": 409,
    "ERR_ATTESTATION_NOT_OPEN": 409,
    "ERR_CLAIM_NOT_REVIEWABLE": 409,
    "ERR_TRANSFER_NOT_PENDING": 409,
    "ERR_DEVICE_NOT_ARMED": 409,
    # ---- safety / constraint / temporal ----
    "ERR_UNRESOLVED_BURST_BLOCKS_REOPEN": 409,
    "ERR_DEVICE_TRANSFER_LOCKED": 409,
    "ERR_MODE_TRANSITION_FORBIDDEN": 409,
    "ERR_SNOOZE_COOLDOWN_ACTIVE": 409,
    "ERR_INSTALL_PRESSURE_TEST_FAILED": 422,
    "ERR_BASELINE_NOT_COMPLETE": 409,
    "ERR_READING_IN_FUTURE": 422,
    "ERR_READING_TOO_OLD": 422,
    "ERR_READING_OUT_OF_ORDER": 409,
    "ERR_IRRIGATION_WINDOW_OVERLAP": 409,
    "ERR_IRRIGATION_NOT_ENABLED": 409,
    "ERR_ATTESTATION_PERIOD_OVERLAP": 409,
    "ERR_ATTESTATION_PERIOD_NOT_CONTIGUOUS": 409,
    "ERR_ATTESTATION_PERIOD_NOT_ENDED": 409,
    "ERR_POLICY_TERMINATED": 409,
    "ERR_NO_QUALIFYING_EVENT": 409,
    "ERR_CLAIM_WINDOW_EXPIRED": 409,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_UNRESOLVED_EVENTS_BLOCK_TRANSFER": 409,
    "ERR_TRANSFER_WINDOW_EXPIRED": 409,
    "ERR_TRANSFER_TARGET_INVALID": 409,
    "ERR_DEVICE_NOT_TRANSFERABLE": 409,
    # ---- fiscal ----
    "ERR_ANNUAL_PAYOUT_CAP_EXCEEDED": 422,
    "ERR_OPEN_PAYOUT_BLOCKS_DEACTIVATION": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def bad_request(message="The request body is malformed or violates a field constraint."):
    return ApiError("ERR_INVALID_REQUEST", message)
