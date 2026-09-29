"""The 53-entry error catalogue and the exception used to raise them.

Every rejection in the system is raised as ApiError; the Flask error handler in
app.py renders it into the standard error envelope. The catalogue is keyed by
error_id and carries the HTTP status from PRD section 5, so a handler never has
to remember a status code.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        entry = ERROR_CATALOG.get(error_id)
        self.http_status = entry[0] if entry else 400
        self.message = message or (entry[1] if entry else error_id)


# error_id -> (http_status, default message)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are required."),
    "ERR_UNAUTHORIZED": (403, "This role may not perform this operation."),
    "ERR_INVALID_REQUEST": (400, "The request is malformed."),
    "ERR_PRACTICE_NOT_FOUND": (404, "No practice with that identifier exists."),
    "ERR_NURSE_NOT_FOUND": (404, "No nurse with that identifier exists."),
    "ERR_PATIENT_NOT_FOUND": (404, "No patient with that identifier exists."),
    "ERR_PROTOCOL_NOT_FOUND": (404, "No symptom protocol with that identifier exists."),
    "ERR_TRIAGE_CALL_NOT_FOUND": (404, "No triage call with that identifier exists."),
    "ERR_ASSESSMENT_NOT_FOUND": (404, "No protocol assessment with that identifier exists."),
    "ERR_DISPOSITION_NOT_FOUND": (404, "No disposition with that identifier exists."),
    "ERR_CALLBACK_TASK_NOT_FOUND": (404, "No callback task with that identifier exists."),
    "ERR_WARM_TRANSFER_NOT_FOUND": (404, "No warm transfer with that identifier exists."),
    "ERR_COVERAGE_WINDOW_NOT_FOUND": (404, "No coverage window with that identifier exists."),
    "ERR_NOT_ASSIGNED_NURSE": (403, "The acting nurse is not assigned to this work item."),
    "ERR_PRACTICE_SCOPE_VIOLATION": (403, "A practice liaison may only read its own practice's data."),
    "ERR_PRACTICE_SUSPENDED": (409, "The practice is suspended."),
    "ERR_CALL_INVALID_STATE": (409, "The call is not in a state that permits this transition."),
    "ERR_ASSESSMENT_SUPERSEDED": (409, "The referenced assessment has been superseded."),
    "ERR_DISPOSITION_INVALID_STATE": (409, "The disposition is not in a state that permits this transition."),
    "ERR_CALLBACK_INVALID_STATE": (409, "The callback task is not in a state that permits this transition."),
    "ERR_TRANSFER_INVALID_STATE": (409, "The warm transfer is not in a state that permits this transition."),
    "ERR_COVERAGE_WINDOW_INVALID_STATE": (409, "The coverage window is not a DRAFT."),
    "ERR_STALE_CALL_VERSION": (412, "The supplied expected_call_version does not match the call's version."),
    "ERR_NURSE_NOT_LICENSED_IN_STATE": (409, "The nurse holds no active licence in the caller's state."),
    "ERR_MINOR_REQUIRES_GUARDIAN_CONSENT": (422, "A minor may not consent for themselves."),
    "ERR_CONSENT_RECORDING_REQUIRED": (422, "This practice requires a recording reference for consent."),
    "ERR_OVERRIDE_DOCUMENTATION_REQUIRED": (422, "An override requires a reason code and a narrative of at least 40 characters."),
    "ERR_DEESCALATION_REQUIRES_CHARGE_NURSE": (403, "Only a charge nurse may soften a recommendation."),
    "ERR_EMERGENCY_DEESCALATION_FORBIDDEN": (422, "An emergency recommendation may not be de-escalated."),
    "ERR_OVERRIDE_STEP_LIMIT": (422, "An override may move at most one severity step."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The nurse who determined this disposition may not perform this operation."),
    "ERR_WARM_TRANSFER_INCOMPLETE": (409, "The call requires a completed warm-transfer handoff."),
    "ERR_PATIENT_PRACTICE_MISMATCH": (409, "The patient does not belong to the call's practice."),
    "ERR_ASSESSMENT_CALL_MISMATCH": (409, "The assessment does not belong to the supplied call."),
    "ERR_CALLBACK_NOT_RESOLVED": (409, "The disposition's callback task is not yet resolved."),
    "ERR_NO_ACTIVE_COVERAGE": (409, "No active coverage window authorises this after-hours call."),
    "ERR_CALLBACK_PAST_DUE": (409, "A high-risk callback may not be verified after its deadline."),
    "ERR_REOPEN_WINDOW_EXPIRED": (409, "The 72-hour reopen window has expired."),
    "ERR_OUTCOME_PREDATES_DISPOSITION": (422, "The observed outcome predates the disposition."),
    "ERR_SHIFT_OVERLAP": (409, "The shift overlaps an existing shift of this nurse."),
    "ERR_COVERAGE_WINDOW_CONFLICT": (409, "The coverage window conflicts with an existing window of this practice."),
    "ERR_PROTOCOL_INACTIVE": (409, "The symptom protocol is retired."),
    "ERR_PROTOCOL_AGE_INELIGIBLE": (422, "The scored age falls outside the protocol's eligibility band."),
    "ERR_MATCH_CONFIDENCE_TOO_LOW": (422, "A non-MRN match requires at least 80 percent confidence."),
    "ERR_INVALID_LOCATION": (422, "The captured location is invalid."),
    "ERR_LOCATION_STATE_MISMATCH": (409, "The location state does not match the caller's state."),
    "ERR_WARM_TRANSFER_NOT_INDICATED": (409, "This call does not require a warm transfer."),
    "ERR_WARM_TRANSFER_ALREADY_OPEN": (409, "A warm transfer for this call is already in play."),
    "ERR_OUTCOME_ALREADY_RECORDED": (409, "An audit record for this disposition already exists."),
    "ERR_LOCATION_CONFIDENCE_TOO_LOW": (422, "Location confidence below 75 percent cannot be confirmed."),
    "ERR_NURSE_AT_CAPACITY": (409, "The preferred nurse is at their concurrent-call cap."),
    "ERR_NO_LICENSED_NURSE_AVAILABLE": (409, "No licensed nurse is available for this call."),
    "ERR_PRACTICE_COMPLIANCE_HOLD": (409, "The practice is under compliance review."),
}


def bad_request(detail):
    return ApiError("ERR_INVALID_REQUEST", detail)
