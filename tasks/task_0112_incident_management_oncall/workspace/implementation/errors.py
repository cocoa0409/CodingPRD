"""Error catalog. error_id -> http_status (PRD Section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_HTTP_STATUS.get(error_id, 400)


ERROR_HTTP_STATUS = {
    # auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    # existence
    "ERR_SERVICE_NOT_FOUND": 404,
    "ERR_RESPONDER_NOT_FOUND": 404,
    "ERR_SCHEDULE_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_WAR_ROOM_NOT_FOUND": 404,
    "ERR_POSTMORTEM_NOT_FOUND": 404,
    "ERR_ACTION_ITEM_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    # not enumerated in the PRD catalog but needed for the two FK-only reads
    # (escalation tier, page attempt); plain 404 for a missing single resource.
    "ERR_TIER_NOT_FOUND": 404,
    "ERR_PAGE_ATTEMPT_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_INTERVAL": 422,
    # incident state
    "ERR_INCIDENT_NOT_TRIGGERED": 409,
    "ERR_INCIDENT_NOT_ACKNOWLEDGED": 409,
    "ERR_INCIDENT_NOT_RESOLVED": 409,
    "ERR_NO_ESCALATION_TARGET": 409,
    # postmortem / action item state
    "ERR_POSTMORTEM_NOT_DRAFT": 409,
    "ERR_POSTMORTEM_NOT_IN_REVIEW": 409,
    "ERR_OPEN_ACTION_ITEMS": 409,
    "ERR_ACTION_ITEM_NOT_OPEN": 409,
    "ERR_ACTION_ITEM_NOT_IN_PROGRESS": 409,
    "ERR_ACTION_ITEM_TERMINAL": 409,
    "ERR_NOT_ACTION_ITEM_OWNER": 403,
    # window / war room state
    "ERR_WINDOW_NOT_SCHEDULED": 409,
    "ERR_WINDOW_NOT_ACTIVE": 409,
    "ERR_WAR_ROOM_NOT_OPEN": 409,
    # paging / safety
    "ERR_RESPONDER_NOT_PAGED": 403,
    # temporal overlap
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_WINDOW_OVERLAP": 409,
    # uniqueness
    "ERR_POSTMORTEM_EXISTS": 409,
    "ERR_WAR_ROOM_EXISTS": 409,
    "ERR_DUPLICATE_TIER_LEVEL": 409,
    # concurrency
    "ERR_STALE_VERSION": 412,
}
