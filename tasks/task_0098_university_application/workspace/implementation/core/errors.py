"""Error catalog and custom exception for the API."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, error_id: str, message: str = "", http_status: int = 400) -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status


# Error catalog: error_id -> (http_status, default_message)
ERROR_CATALOG: dict[str, tuple[int, str]] = {
    # auth
    "ERR_AUTH_MISSING": (401, "Required auth headers (X-User-Role, X-User-ID) missing or empty."),
    "ERR_AUTH_INVALID_ROLE": (403, "X-User-Role is not one of the declared roles."),
    "ERR_FORBIDDEN": (403, "Authenticated role is not permitted to invoke this endpoint or operate on this resource."),
    # not-found
    "ERR_APPLICANT_NOT_FOUND": (404, "Referenced Applicant id does not exist."),
    "ERR_UNIVERSITY_NOT_FOUND": (404, "Referenced University id does not exist."),
    "ERR_PROGRAM_NOT_FOUND": (404, "Referenced Program id does not exist."),
    "ERR_APPLICATION_NOT_FOUND": (404, "Referenced Application id does not exist."),
    "ERR_RESOURCE_NOT_FOUND": (404, "Referenced resource does not exist."),
    # input
    "ERR_VALIDATION": (400, "Request body fails type / shape / range validation."),
    "ERR_ESSAY_LENGTH": (422, "EssaySubmission.body length outside [250, 6500] characters."),
    # state / concurrency
    "ERR_INVALID_STATE": (409, "Entity is not in a state where this operation is valid."),
    "ERR_VERSION_CONFLICT": (409, "Provided version does not match the entity's current version."),
    "ERR_SWEEP_IN_PROGRESS": (409, "A YieldSweep is holding the university-scoped lock."),
    # business: ED / submission gates
    "ERR_ED_ALREADY_BOUND": (409, "Applicant already has an active Early Decision commitment."),
    "ERR_ED_DEADLINE_PASSED": (409, "Early Decision submission window has closed."),
    "ERR_DEADLINE_PASSED": (409, "Submission deadline has passed for this university/round."),
    "ERR_ESSAY_NOT_CUSTOMIZED": (422, "Application essay customization_score below 0.30."),
    "ERR_INSUFFICIENT_RECOMMENDATIONS": (422, "Insufficient SUBMITTED recommendation letters."),
    "ERR_WEAK_LETTER": (422, "Recommendation letter has fewer than 200 words."),
    "ERR_MISSING_EFC": (422, "Applicant is missing the EFC field required by the aid method."),
    # business: capacity / enrollment
    "ERR_PROGRAM_AT_CAPACITY": (409, "Admitting this Application would exceed Program.capacity."),
    "ERR_ENROLLMENT_DEADLINE_PASSED": (409, "Application.enrollment_deadline has passed."),
    "ERR_OFFER_EXPIRED": (409, "WaitlistEntry.offer_expires_at has passed."),
    "ERR_ALREADY_ENROLLED_ELSEWHERE": (409, "Applicant already has another Application in ENROLLED state."),
}


def raise_error(error_id: str, message: str | None = None) -> None:
    http, default = ERROR_CATALOG.get(error_id, (400, error_id))
    raise ApiError(error_id, message or default, http)
