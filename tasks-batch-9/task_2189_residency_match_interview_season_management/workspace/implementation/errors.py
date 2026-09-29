"""Error catalogue (PRD section 5) and the exception type carrying it."""

# error_id -> HTTP status
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_RANK_LIST_VERSION": 412,
    "ERR_STALE_WAVE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_CONFLICT_OF_INTEREST": 422,
    "ERR_UNRESOLVED_COMMUNICATION_FLAG": 422,
    "ERR_CROSS_REFERENCE_MISMATCH": 422,
    "ERR_INVITATION_EXPIRED": 409,
    "ERR_SOAP_OFFER_EXPIRED": 409,
    "ERR_INTERVIEWER_DOUBLE_BOOKED": 409,
    "ERR_WAVE_WINDOW_CONFLICT": 409,
    "ERR_SLOT_TIMING_VIOLATION": 409,
    "ERR_CERTIFICATION_DEADLINE_PASSED": 409,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_SCREENING_FILTER_FAILED": 422,
    "ERR_INSUFFICIENT_EVALUATIONS": 422,
    "ERR_RANK_POSITION_SEQUENCE": 422,
    "ERR_SLOT_FULL": 409,
    "ERR_WAVE_CAPACITY_REACHED": 409,
    "ERR_SOAP_BUDGET_EXCEEDED": 409,
    "ERR_RANK_LIST_TOO_LONG": 409,
    "ERR_CREDENTIALS_INCOMPLETE": 409,
    "ERR_NO_POSITIONS_AVAILABLE": 409,
    # Only ever raised by an implementation defect.
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Both X-User-ID and X-User-Role headers are required.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this endpoint.",
    "ERR_OWNERSHIP_MISMATCH": "The acting identity does not own the target resource.",
    "ERR_RESOURCE_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_VALIDATION": "The request body or query string is invalid.",
    "ERR_INVALID_STATE": "The requested transition is not admissible from the current state.",
    "ERR_STALE_RANK_LIST_VERSION": "expected_rank_list_version does not match the rank list version.",
    "ERR_STALE_WAVE_VERSION": "expected_wave_version does not match the interview wave version.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from certifying the list.",
    "ERR_CONFLICT_OF_INTEREST": "The faculty member declared a conflict of interest with this applicant.",
    "ERR_UNRESOLVED_COMMUNICATION_FLAG": "The application carries an unresolved communication flag.",
    "ERR_CROSS_REFERENCE_MISMATCH": "The referenced rows do not belong to the same aggregate.",
    "ERR_INVITATION_EXPIRED": "The invitation has lapsed.",
    "ERR_SOAP_OFFER_EXPIRED": "The SOAP offer has lapsed.",
    "ERR_INTERVIEWER_DOUBLE_BOOKED": "The interviewer already holds an overlapping assigned slot.",
    "ERR_WAVE_WINDOW_CONFLICT": "The wave window is not separated from an existing wave by 48 hours.",
    "ERR_SLOT_TIMING_VIOLATION": "The slot timing constraint is violated.",
    "ERR_CERTIFICATION_DEADLINE_PASSED": "The rank list certification deadline has passed.",
    "ERR_DUPLICATE_RESOURCE": "A resource with the same uniqueness key already exists.",
    "ERR_SCREENING_FILTER_FAILED": "The application does not clear the program's screening filters.",
    "ERR_INSUFFICIENT_EVALUATIONS": "Not enough evaluations exist for this operation.",
    "ERR_RANK_POSITION_SEQUENCE": "The rank position sequence is not contiguous.",
    "ERR_SLOT_FULL": "The interview slot has no free seat.",
    "ERR_WAVE_CAPACITY_REACHED": "The wave can absorb no further invitation.",
    "ERR_SOAP_BUDGET_EXCEEDED": "The program's SOAP offer budget is exhausted.",
    "ERR_RANK_LIST_TOO_LONG": "The rank list may not exceed ten times the program quota.",
    "ERR_CREDENTIALS_INCOMPLETE": "Every mandatory credential item must be verified first.",
    "ERR_NO_POSITIONS_AVAILABLE": "The program has no unfilled position left.",
    "ERR_INTERNAL": "Internal server error.",
}


class ApiError(Exception):
    """Domain refusal carrying an error_id from the catalogue."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)
