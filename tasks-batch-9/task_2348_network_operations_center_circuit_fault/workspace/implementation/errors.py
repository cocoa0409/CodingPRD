"""Error catalog (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # --- authentication / authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CARRIER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence ---
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_CIRCUIT_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_PATH_NOT_FOUND": 404,
    "ERR_SEGMENT_NOT_FOUND": 404,
    "ERR_ALARM_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_TEST_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    # --- schema ---
    "ERR_INVALID_REQUEST": 400,
    "ERR_TIMESTAMP_RANGE_INVALID": 422,
    # --- own state ---
    "ERR_ALARM_ALREADY_CLEARED": 409,
    "ERR_RESPONSE_SEQUENCE_INVALID": 409,
    "ERR_INCIDENT_ALREADY_RESOLVED": 409,
    "ERR_ESCALATION_SEQUENCE_INVALID": 409,
    "ERR_TICKET_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_WINDOW_STATE_INVALID": 409,
    "ERR_TEST_STATE_INVALID": 409,
    "ERR_ORDER_STATE_INVALID": 409,
    "ERR_REVIEW_ALREADY_DECIDED": 409,
    # --- related state ---
    "ERR_TICKET_NOT_CLOSED": 409,
    "ERR_INCIDENT_NOT_MITIGATED": 409,
    "ERR_OPEN_ALARMS_PRESENT": 409,
    "ERR_CARRIER_TICKET_OPEN": 409,
    "ERR_CIRCUIT_SLATED_FOR_REPLACEMENT": 409,
    # --- optimistic concurrency ---
    "ERR_STALE_CARRIER_TICKET_VERSION": 412,
    "ERR_STALE_CIRCUIT_VERSION": 412,
    # --- reference shape ---
    "ERR_SEGMENT_TARGET_INVALID": 422,
    "ERR_ALARM_SOURCE_INVALID": 422,
    "ERR_CIRCUIT_INCIDENT_MISMATCH": 422,
    "ERR_LEG_NOT_FOUND": 422,
    # --- uniqueness / admissibility ---
    "ERR_CARRIER_CODE_DUPLICATE": 409,
    "ERR_CIRCUIT_IDENTIFIER_DUPLICATE": 409,
    "ERR_DEVICE_HOSTNAME_DUPLICATE": 409,
    "ERR_SEGMENT_POSITION_TAKEN": 409,
    "ERR_CARRIER_REFERENCE_DUPLICATE": 409,
    "ERR_DUPLICATE_OPEN_TICKET": 409,
    "ERR_CLAIM_ALREADY_OPEN": 409,
    "ERR_CIRCUIT_NOT_MONITORED": 409,
    "ERR_CIRCUIT_NOT_FAULTED": 409,
    # --- operation specific business rules ---
    "ERR_TIER_SEQUENCE_INVALID": 422,
    "ERR_TIER_CEILING_REACHED": 409,
    "ERR_TEST_EVIDENCE_MISSING": 422,
    "ERR_TEST_EVIDENCE_CONTRADICTS_NO_FAULT": 409,
    "ERR_EXEC_ESCALATION_NOT_ALLOWED": 422,
    "ERR_REDUNDANCY_RISK_UNACKNOWLEDGED": 422,
    "ERR_PATH_NOT_PROTECTED": 409,
    "ERR_MAINTENANCE_IN_EFFECT": 409,
    "ERR_FAILOVER_RESULT_INCONSISTENT": 422,
    "ERR_UPGRADE_TARGET_INVALID": 422,
    # --- temporal exclusivity / dwell ---
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_FAILOVER_TEST_CONFLICT": 409,
    "ERR_READING_OUT_OF_ORDER": 409,
    "ERR_TIER_DWELL_NOT_MET": 409,
    "ERR_SOAK_WINDOW_NOT_ELAPSED": 409,
    "ERR_WINDOW_NOT_IN_EFFECT": 409,
    "ERR_TEST_WINDOW_NOT_IN_EFFECT": 409,
    "ERR_ESCALATION_PREMATURE": 409,
    # --- fiscal admissibility ---
    "ERR_NO_SLA_BREACH": 422,
    "ERR_CLAIM_BELOW_MINIMUM": 422,
    "ERR_CREDIT_AMOUNT_MISMATCH": 422,
    "ERR_REPLACEMENT_NOT_JUSTIFIED": 422,
    "ERR_RETAIN_NOT_JUSTIFIED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = status if status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    text = error_id[4:] if error_id.startswith("ERR_") else error_id
    return text.replace("_", " ").lower().capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)
