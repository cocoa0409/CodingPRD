"""Error catalog: every error_id with its HTTP status, plus the ApiError type."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"  # 400
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"  # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"  # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"  # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"  # 409
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"  # 403
ERR_PROFILE_INACTIVE = "ERR_PROFILE_INACTIVE"  # 409
ERR_INDICATION_NOT_LOCKED = "ERR_INDICATION_NOT_LOCKED"  # 409
ERR_DEVIATION_NOT_USABLE = "ERR_DEVIATION_NOT_USABLE"  # 409
ERR_COMPONENT_INCOMPLETE = "ERR_COMPONENT_INCOMPLETE"  # 409
ERR_DUPLICATE_PROFILE = "ERR_DUPLICATE_PROFILE"  # 409
ERR_DUPLICATE_OPEN_FILING = "ERR_DUPLICATE_OPEN_FILING"  # 409
ERR_OPEN_OBJECTIONS = "ERR_OPEN_OBJECTIONS"  # 409
ERR_RATEBOOK_OVERLAP = "ERR_RATEBOOK_OVERLAP"  # 409
ERR_WAVE_GAP_VIOLATION = "ERR_WAVE_GAP_VIOLATION"  # 409
ERR_WAVE_NOT_REVERSIBLE = "ERR_WAVE_NOT_REVERSIBLE"  # 409
ERR_EFFECTIVE_LEAD_VIOLATION = "ERR_EFFECTIVE_LEAD_VIOLATION"  # 422
ERR_EFFECTIVE_DATE_NOT_REACHED = "ERR_EFFECTIVE_DATE_NOT_REACHED"  # 409
ERR_DISAPPROVAL_WINDOW_CLOSED = "ERR_DISAPPROVAL_WINDOW_CLOSED"  # 409
ERR_NOTICE_DEADLINE_PASSED = "ERR_NOTICE_DEADLINE_PASSED"  # 409
ERR_WAVE_WINDOW_INVALID = "ERR_WAVE_WINDOW_INVALID"  # 422
ERR_CHANGE_EXCEEDS_MAX = "ERR_CHANGE_EXCEEDS_MAX"  # 422
ERR_CAP_ABOVE_REGULATORY_MAX = "ERR_CAP_ABOVE_REGULATORY_MAX"  # 422


def err(error_id):
    """Build an ApiError with the catalogued HTTP status for the id."""
    status = _CATALOG[error_id]
    return ApiError(error_id, _MESSAGES.get(error_id, error_id), status)


_CATALOG = {
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER: 400,
    ERR_FORBIDDEN_FOR_ROLE: 403,
    ERR_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 400,
    ERR_STALE_VERSION: 412,
    ERR_INVALID_STATE: 409,
    ERR_SOD_VIOLATION: 403,
    ERR_PROFILE_INACTIVE: 409,
    ERR_INDICATION_NOT_LOCKED: 409,
    ERR_DEVIATION_NOT_USABLE: 409,
    ERR_COMPONENT_INCOMPLETE: 409,
    ERR_DUPLICATE_PROFILE: 409,
    ERR_DUPLICATE_OPEN_FILING: 409,
    ERR_OPEN_OBJECTIONS: 409,
    ERR_RATEBOOK_OVERLAP: 409,
    ERR_WAVE_GAP_VIOLATION: 409,
    ERR_WAVE_NOT_REVERSIBLE: 409,
    ERR_EFFECTIVE_LEAD_VIOLATION: 422,
    ERR_EFFECTIVE_DATE_NOT_REACHED: 409,
    ERR_DISAPPROVAL_WINDOW_CLOSED: 409,
    ERR_NOTICE_DEADLINE_PASSED: 409,
    ERR_WAVE_WINDOW_INVALID: 422,
    ERR_CHANGE_EXCEEDS_MAX: 422,
    ERR_CAP_ABOVE_REGULATORY_MAX: 422,
}

_MESSAGES = {
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER: "X-User-ID or X-User-Role header missing or malformed",
    ERR_FORBIDDEN_FOR_ROLE: "Caller role not permitted on this endpoint",
    ERR_NOT_FOUND: "Path id or body FK reference does not resolve",
    ERR_INVALID_REQUEST: "Malformed body: missing required field, unknown field, wrong type, invalid enum member, non-positive amounts, bad date format",
    ERR_STALE_VERSION: "expected version does not equal the parent's current version",
    ERR_INVALID_STATE: "Resource is in a state from which the requested transition does not exist",
    ERR_SOD_VIOLATION: "Segregation of duties breached: indication approver equals prepared_by_user_id",
    ERR_PROFILE_INACTIVE: "StateRegulatoryProfile is SUSPENDED (or absent-but-required ACTIVE) for the operation",
    ERR_INDICATION_NOT_LOCKED: "Referenced indication is not LOCKED",
    ERR_DEVIATION_NOT_USABLE: "An attached deviation is WITHDRAWN or REJECTED at submit time",
    ERR_COMPONENT_INCOMPLETE: "mark-ready without the required FINAL component set for the filing_type",
    ERR_DUPLICATE_PROFILE: "A StateRegulatoryProfile already exists for (product_id, state_code)",
    ERR_DUPLICATE_OPEN_FILING: "A RateFiling in an open state already exists for (product_id, state_code)",
    ERR_OPEN_OBJECTIONS: "Approve attempted while objections remain non-terminal",
    ERR_RATEBOOK_OVERLAP: "Another EFFECTIVE filing for the same rate book has actual_effective_date >= this filing's",
    ERR_WAVE_GAP_VIOLATION: "Wave window violates the minimum separation against an existing wave of the same rate book",
    ERR_WAVE_NOT_REVERSIBLE: "Post-effective disapproval blocked: a wave of this filing is COMPLETED",
    ERR_EFFECTIVE_LEAD_VIOLATION: "proposed_effective_date violates the filing method's lead-time rule",
    ERR_EFFECTIVE_DATE_NOT_REACHED: "Clock is before the (actual) effective / renewal date required for the transition",
    ERR_DISAPPROVAL_WINDOW_CLOSED: "Post-effective disapproval attempted after the statutory window",
    ERR_NOTICE_DEADLINE_PASSED: "send-notice attempted after notice_due_date",
    ERR_WAVE_WINDOW_INVALID: "wave_end_date < wave_start_date",
    ERR_CHANGE_EXCEEDS_MAX: "proposed_change_pct exceeds profile.max_single_change_pct",
    ERR_CAP_ABOVE_REGULATORY_MAX: "wave cap_pct exceeds profile.max_single_change_pct",
}
