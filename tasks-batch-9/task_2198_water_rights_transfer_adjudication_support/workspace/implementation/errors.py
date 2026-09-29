"""Error catalogue and the ApiError exception carrying error_id / message / http_status."""

# Complete error catalogue: error_id -> HTTP status (PRD Section 5).
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CLAIMANT_NOT_FOUND": 404,
    "ERR_WATER_RIGHT_NOT_FOUND": 404,
    "ERR_POINT_OF_DIVERSION_NOT_FOUND": 404,
    "ERR_BENEFICIAL_USE_RECORD_NOT_FOUND": 404,
    "ERR_HCU_STUDY_NOT_FOUND": 404,
    "ERR_TRANSFER_APPLICATION_NOT_FOUND": 404,
    "ERR_INJURY_ANALYSIS_NOT_FOUND": 404,
    "ERR_PROTEST_NOT_FOUND": 404,
    "ERR_APPROVAL_CONDITION_NOT_FOUND": 404,
    "ERR_WATER_BANK_ACCOUNT_NOT_FOUND": 404,
    "ERR_LEASE_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_DECREE_DOCKET_NOT_FOUND": 404,
    "ERR_ADJUDICATION_CLAIM_NOT_FOUND": 404,
    "ERR_DUPLICATE_RIGHT_NUMBER": 409,
    "ERR_DUPLICATE_DOCKET_NUMBER": 409,
    "ERR_DUPLICATE_USE_YEAR": 409,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_DUPLICATE_PROTEST": 409,
    "ERR_STALE_RIGHT_VERSION": 412,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_RIGHT_NOT_TRANSFERABLE": 409,
    "ERR_DOCKET_PHASE_INVALID": 409,
    "ERR_CLAIM_NOT_VERIFIED": 409,
    "ERR_CONDITION_FEE_OUTSTANDING": 409,
    "ERR_ACCOUNT_POSTURE_BLOCKED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CLAIMANT_NOT_IN_GOOD_STANDING": 403,
    "ERR_INJURY_ANALYSIS_MISSING": 422,
    "ERR_VIOLATION_UNRESOLVED": 409,
    "ERR_WINDOW_STILL_OPEN": 409,
    "ERR_PROTEST_WINDOW_CLOSED": 422,
    "ERR_CLAIM_FILING_CLOSED": 422,
    "ERR_LEASE_WINDOW_TIMING": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_SELF_PROTEST_FORBIDDEN": 422,
    "ERR_SELF_OBJECTION_FORBIDDEN": 422,
    "ERR_LEASE_WINDOW_CONFLICT": 409,
    "ERR_POD_CAPACITY_EXCEEDED": 409,
    "ERR_POD_NOT_AUTHORIZED": 409,
    # PRD §3.9: "the right's `bank_enrolled` flag must be set, otherwise
    # `ERR_RIGHT_NOT_BANK_ENROLLED` (422)", matching PRD §5's catalogue entry.
    "ERR_RIGHT_NOT_BANK_ENROLLED": 422,
    "ERR_TRANSFERABLE_VOLUME_EXCEEDED": 422,
    "ERR_INSUFFICIENT_BANK_CREDIT": 422,
    "ERR_UNMITIGATED_INJURY": 422,
    "ERR_MITIGATION_INSUFFICIENT": 422,
    "ERR_INSUFFICIENT_USE_HISTORY": 422,
    "ERR_NO_VERIFIED_USE_EVIDENCE": 422,
    "ERR_FORFEITURE_NOT_ELIGIBLE": 422,
    "ERR_RECOMMENDATION_EXCEEDS_CLAIM": 422,
    "ERR_OFFSET_EXCEEDS_CLAIM": 422,
    "ERR_APPLICATION_SCOPE_INCOMPLETE": 422,
    "ERR_STUDY_RIGHT_MISMATCH": 422,
    "ERR_POD_RIGHT_MISMATCH": 422,
    "ERR_DOCKET_CHILDREN_NOT_READY": 422,
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message if message else _default_message(error_id)
        self.http_status = (
            http_status if http_status is not None else ERROR_CATALOG.get(error_id, 400)
        )


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").capitalize()


# ---------------------------------------------------------------------------
# Convenience raisers used pervasively by the route modules.
# ---------------------------------------------------------------------------

def bad_request(message="Request payload is malformed or violates a field constraint."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def not_found(error_id, message=None):
    raise ApiError(error_id, message)


def conflict(error_id, message=None):
    raise ApiError(error_id, message)
