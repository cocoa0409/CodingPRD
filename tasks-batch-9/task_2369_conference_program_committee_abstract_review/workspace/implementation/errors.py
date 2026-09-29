"""Error catalogue (PRD section 5 / SCAFFOLD section 1.6)."""

ERROR_STATUS = {
    # --- auth / identity -------------------------------------------------
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_IDENTITY_NOT_FOUND": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # --- generic schema --------------------------------------------------
    "ERR_VALIDATION": 400,
    # --- existence -------------------------------------------------------
    "ERR_CONFERENCE_NOT_FOUND": 404,
    "ERR_CATEGORY_NOT_FOUND": 404,
    "ERR_AUTHOR_NOT_FOUND": 404,
    "ERR_ABSTRACT_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_DECLARATION_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_DISCREPANCY_CASE_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_ACCREDITATION_NOT_FOUND": 404,
    "ERR_DISCLOSURE_NOT_FOUND": 404,
    "ERR_CHANGE_REQUEST_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    # --- optimistic concurrency -----------------------------------------
    "ERR_STALE_CONFERENCE_VERSION": 412,
    "ERR_STALE_SESSION_VERSION": 412,
    # --- state -----------------------------------------------------------
    "ERR_CONFERENCE_STATE_INVALID": 409,
    "ERR_ABSTRACT_STATE_INVALID": 409,
    "ERR_MEMBER_STATE_INVALID": 409,
    "ERR_REVIEW_STATE_INVALID": 409,
    "ERR_CASE_STATE_INVALID": 409,
    "ERR_SESSION_STATE_INVALID": 409,
    "ERR_SLOT_STATE_INVALID": 409,
    "ERR_ACCREDITATION_STATE_INVALID": 409,
    "ERR_DISCLOSURE_STATE_INVALID": 409,
    "ERR_CHANGE_REQUEST_STATE_INVALID": 409,
    # --- conflict of interest / segregation of duties --------------------
    "ERR_REVIEWER_CONFLICT": 409,
    "ERR_ARBITER_CONFLICT": 409,
    "ERR_SEGREGATION_VIOLATION": 409,
    "ERR_ACCREDITATION_SELF_VALIDATION": 409,
    "ERR_COI_NOT_DECLARED": 409,
    # --- sanctions -------------------------------------------------------
    "ERR_AUTHOR_BARRED": 403,
    # --- disclosure ------------------------------------------------------
    "ERR_DISCLOSURE_INCOMPLETE": 409,
    "ERR_DISCLOSURE_ABSTRACT_MISMATCH": 422,
    # --- referential coherence ------------------------------------------
    "ERR_CATEGORY_CONFERENCE_MISMATCH": 422,
    "ERR_FORMAT_NOT_ALLOWED": 422,
    "ERR_SESSION_THEME_MISMATCH": 422,
    "ERR_SESSION_FORMAT_MISMATCH": 422,
    "ERR_PRESENTER_NOT_ON_ABSTRACT": 422,
    "ERR_CATEGORY_NOT_CME_ELIGIBLE": 422,
    # --- temporal --------------------------------------------------------
    "ERR_CFA_DEADLINE_PASSED": 422,
    "ERR_REVIEW_PAST_DUE": 422,
    "ERR_PROGRAM_FROZEN": 409,
    "ERR_EMBARGO_WINDOW_INVALID": 422,
    "ERR_INVALID_DATE_RANGE": 422,
    # --- abstract formatting --------------------------------------------
    "ERR_ABSTRACT_FORMAT_INVALID": 422,
    # --- review workflow -------------------------------------------------
    "ERR_DUPLICATE_REVIEW_ASSIGNMENT": 409,
    "ERR_NO_ELIGIBLE_REVIEWER": 422,
    "ERR_INSUFFICIENT_REVIEWS": 409,
    "ERR_OPEN_DISCREPANCY": 409,
    "ERR_OVERRIDE_NOT_PERMITTED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_CFA_EXTENSION_LIMIT": 409,
    "ERR_REVIEW_REOPEN_LIMIT": 409,
    "ERR_UNDECIDED_ABSTRACTS_REMAIN": 409,
    "ERR_MEMBER_STILL_CHAIRING": 409,
    "ERR_EMBARGO_NOT_SET": 409,
    "ERR_NOT_NEWSWORTHY": 422,
    "ERR_EMPTY_SESSION": 409,
    "ERR_SESSION_NOT_ACCREDITED": 409,
    # --- exclusivity / overlap ------------------------------------------
    "ERR_ROOM_TIME_CONFLICT": 409,
    "ERR_CHAIR_TIME_CONFLICT": 409,
    "ERR_PRESENTER_TIME_CONFLICT": 409,
    # --- packing ---------------------------------------------------------
    "ERR_SESSION_SLOT_CAPACITY_REACHED": 422,
    "ERR_DUPLICATE_SLOT_POSITION": 422,
    "ERR_SESSION_DURATION_EXCEEDED": 422,
    # --- registration ----------------------------------------------------
    "ERR_AUTHOR_NOT_REGISTERED": 422,
    # --- quota ceilings --------------------------------------------------
    "ERR_FORMAT_CAPACITY_EXHAUSTED": 422,
    "ERR_CME_POOL_EXHAUSTED": 422,
    "ERR_REVIEWER_LOAD_EXCEEDED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADERS": "X-User-ID and X-User-Role headers are required.",
    "ERR_UNAUTHORIZED": "The presented role is not authorized for this operation.",
    "ERR_IDENTITY_NOT_FOUND": "The presented identity could not be resolved.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own this resource.",
    "ERR_VALIDATION": "The request payload failed schema validation.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
