"""Error catalogue (PRD §5) and the exception type carried through the stack."""

ERROR_HTTP_STATUS = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_EXAM_SUBJECT": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_INSURER_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_EXAMINATION_NOT_FOUND": 404,
    "ERR_EXAM_RECORD_NOT_FOUND": 404,
    # request shape / uniqueness
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    # lifecycle state
    "ERR_CYCLE_STATE_INVALID": 409,
    "ERR_EXAM_NOT_IN_SCOPING": 409,
    "ERR_SCOPE_NOT_LOCKED": 409,
    "ERR_DATA_CALL_NOT_AWAITING_RESPONSE": 409,
    "ERR_DATA_CALL_NOT_RESPONDED": 409,
    "ERR_SAMPLE_ALREADY_REVIEWED": 409,
    "ERR_EXAM_NOT_IN_CRITICISM_PHASE": 409,
    "ERR_CRITICISM_STATE_INVALID": 409,
    "ERR_EXAM_NOT_IN_NEGOTIATION": 409,
    "ERR_ENFORCEMENT_RECORD_STATE_INVALID": 409,
    "ERR_EXAM_NOT_READY_FOR_PUBLICATION": 409,
    "ERR_EXAM_ALREADY_TERMINAL": 409,
    # version pinning
    "ERR_STALE_EXAMINATION_VERSION": 412,
    # business safety
    "ERR_INSURER_NOT_EXAMINABLE": 409,
    "ERR_SCOPE_AREA_NOT_TESTED": 409,
    "ERR_FIELDWORK_NOT_DOCUMENTED": 409,
    "ERR_SAMPLE_SIZE_BELOW_MINIMUM": 422,
    "ERR_REBUTTAL_ROUNDS_EXHAUSTED": 409,
    # temporal occupancy
    "ERR_EXAM_WINDOW_CONFLICT": 409,
    "ERR_DUE_DATE_OUT_OF_WINDOW": 422,
    "ERR_DATA_CALL_WINDOW_CONFLICT": 409,
    # referential prerequisites
    "ERR_CAP_NOT_APPROVED": 409,
    "ERR_ORDER_NOT_EXECUTED": 409,
    "ERR_NO_TOLERANCE_BREACH": 422,
    "ERR_NO_ELIGIBLE_LEAD_STATE": 422,
    # numeric constraints
    "ERR_RECORDS_EXCEED_REQUEST": 422,
    "ERR_SAMPLE_EXCEEDS_POPULATION": 422,
    "ERR_AFFECTED_FILES_EXCEED_ERRORS": 422,
    "ERR_RESPONSE_INCOMPLETE": 409,
    "ERR_CYCLE_SLOTS_EXHAUSTED": 409,
    # fiscal ceilings
    "ERR_PENALTY_CAP_EXCEEDED": 422,
    "ERR_RESTITUTION_NOT_CONSERVED": 409,
}


class ApiError(Exception):
    """Raised anywhere in the request path; rendered by the app error handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def invalid(message="The request payload is malformed."):
    return ApiError("ERR_INVALID_REQUEST", message)
