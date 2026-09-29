"""Error catalog (SCAFFOLD §1.6 / PRD §5)."""

ERROR_CATALOG = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # not found
    "ERR_ASSOCIATION_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_TURNOVER_CASE_NOT_FOUND": 404,
    "ERR_COMPONENT_NOT_FOUND": 404,
    "ERR_DEFECT_CLAIM_NOT_FOUND": 404,
    "ERR_VENDOR_CONTRACT_NOT_FOUND": 404,
    "ERR_SUBSIDY_ENTRY_NOT_FOUND": 404,
    "ERR_RESERVE_STUDY_NOT_FOUND": 404,
    "ERR_RECORDS_ITEM_NOT_FOUND": 404,
    "ERR_AUDIT_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_DIRECTOR_NOT_FOUND": 404,
    "ERR_ASSESSMENT_SCHEDULE_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    # shape
    "ERR_INVALID_REQUEST": 400,
    # concurrency
    "ERR_STALE_ASSOCIATION_VERSION": 412,
    # state
    "ERR_TURNOVER_SETTLED_LOCKED": 409,
    "ERR_TURNOVER_STAGE_INVALID": 409,
    "ERR_TURNOVER_CASE_EXISTS": 409,
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_COMPONENT_MILESTONE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_CONTRACT_STATE_INVALID": 409,
    "ERR_RECORDS_ITEM_STATE_INVALID": 409,
    "ERR_DIRECTOR_STATE_INVALID": 409,
    "ERR_SUBSIDY_ENTRY_ALREADY_REVERSED": 409,
    "ERR_AUDIT_NOT_ISSUABLE": 409,
    "ERR_NOT_IN_DRAFT": 409,
    "ERR_ADEQUACY_NOT_EVALUATED": 409,
    # referential business rules
    "ERR_COMPONENT_NOT_CONVEYED": 409,
    "ERR_SUBSIDY_STILL_ACTIVE": 409,
    "ERR_RESERVE_STUDY_NOT_ADOPTED": 409,
    "ERR_TRANSITION_AUDIT_MISSING": 409,
    "ERR_ASSIGNMENT_CONSENT_REQUIRED": 422,
    "ERR_UNBUILT_AMENITY_OUTSTANDING": 422,
    "ERR_RECORDS_INCOMPLETE": 422,
    # temporal
    "ERR_REPOSE_PERIOD_EXPIRED": 422,
    "ERR_CANCELLATION_WINDOW_CLOSED": 422,
    # occupancy / uniqueness
    "ERR_AUDIT_PERIOD_OVERLAP": 409,
    "ERR_SERVICE_WINDOW_CONFLICT": 409,
    "ERR_DUPLICATE_LOT_NUMBER": 409,
    # thresholds / caps
    "ERR_TURNOVER_THRESHOLD_NOT_MET": 422,
    "ERR_FIXED_TURNOVER_DATE_NOT_REACHED": 422,
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": 422,
    "ERR_SEAT_CAPACITY_EXCEEDED": 422,
    "ERR_OWNER_VOTE_REQUIRED": 422,
    # fiscal
    "ERR_CLAIM_RESERVE_INSUFFICIENT": 422,
    "ERR_SETTLEMENT_BLOCKED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_CATALOG.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").capitalize() + "."


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)
