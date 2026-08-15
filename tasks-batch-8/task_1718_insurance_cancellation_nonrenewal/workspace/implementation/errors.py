"""Error classes and error-ID constants for the carrier API.

Every error_id / HTTP-status pair is taken verbatim from SCAFFOLD.yaml §1.6
and PRD.md §5.
"""


class ApiError(Exception):
    """Exception carrying the scaffold-defined error contract."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_missing_auth_context(message="X-User-ID or X-User-Role header missing or malformed"):
    return ApiError("ERR_MISSING_AUTH_CONTEXT", message, 400)


def err_forbidden_for_role(message="Caller role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", message, 403)


def err_not_found(message="Path id does not resolve to an existing resource"):
    return ApiError("ERR_NOT_FOUND", message, 404)


def err_invalid_request(message="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", message, 400)


def err_invalid_state(message="Target resource not in a state admitting the requested transition"):
    return ApiError("ERR_INVALID_STATE", message, 409)


def err_segregation_of_duties(message="Approver/decider X-User-ID equals the X-User-ID that performed the preceding workflow step"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", message, 403)


def err_ground_role_mismatch(message="INSURED_REQUEST submitted by non-Policyholder, or insurer ground submitted by Policyholder"):
    return ApiError("ERR_GROUND_ROLE_MISMATCH", message, 422)


def err_ground_not_permitted(message="ground_code absent from the ACTIVE profile's permissible_grounds (and not INSURED_REQUEST)"):
    return ApiError("ERR_GROUND_NOT_PERMITTED_IN_STATE", message, 422)


def err_policy_not_active(message="Policy not ACTIVE when opening a cancellation or nonrenewal case"):
    return ApiError("ERR_POLICY_NOT_ACTIVE", message, 409)


def err_policy_not_cancelled(message="Reinstatement or appeal action requires Policy.status = CANCELLED"):
    return ApiError("ERR_POLICY_NOT_CANCELLED", message, 409)


def err_cancellation_already_open(message="An open CancellationCase already exists for this policy"):
    return ApiError("ERR_CANCELLATION_ALREADY_OPEN", message, 409)


def err_nonrenewal_already_open(message="An open NonrenewalCase already exists for this policy"):
    return ApiError("ERR_NONRENEWAL_ALREADY_OPEN", message, 409)


def err_effective_date_too_early(message="scheduled_effective_date earlier than earliest_effective_date"):
    return ApiError("ERR_EFFECTIVE_DATE_TOO_EARLY", message, 422)


def err_notice_set_incomplete(message="Dispatch payload missing the policyholder notice or any per-interest notice"):
    return ApiError("ERR_NOTICE_SET_INCOMPLETE", message, 422)


def err_notice_period_shortfall(message="mailed_on_date + recipient statutory days exceeds scheduled_effective_date"):
    return ApiError("ERR_NOTICE_PERIOD_SHORTFALL", message, 422)


def err_mailing_date_in_future(message="mailed_on_date later than current clock date"):
    return ApiError("ERR_MAILING_DATE_IN_FUTURE", message, 422)


def err_notice_not_mailed(message="Clock sweep blocked: a notice for the case is QUEUED or RETURNED_UNDELIVERABLE"):
    return ApiError("ERR_NOTICE_NOT_MAILED", message, 409)


def err_nonrenewal_deadline_passed(message="Nonrenewal created after notice_deadline_date"):
    return ApiError("ERR_NONRENEWAL_DEADLINE_PASSED", message, 422)


def err_nonrenewal_content_incomplete(message="content_codes_present does not cover the profile's required nonrenewal_content_codes"):
    return ApiError("ERR_NONRENEWAL_CONTENT_INCOMPLETE", message, 422)


def err_nonrenewal_notice_late(message="Nonrenewal notice mailed_on_date after notice_deadline_date"):
    return ApiError("ERR_NONRENEWAL_NOTICE_LATE", message, 422)


def err_reinstatement_window_closed(message="submitted_on_date beyond cancellation_effective_date + reinstatement_window_days"):
    return ApiError("ERR_REINSTATEMENT_WINDOW_CLOSED", message, 422)


def err_reinstatement_limit_reached(message="policy.reinstatements_used >= profile.max_reinstatements"):
    return ApiError("ERR_REINSTATEMENT_LIMIT_REACHED", message, 409)


def err_already_effective(message="Rescission attempted on/after scheduled_effective_date"):
    return ApiError("ERR_ALREADY_EFFECTIVE", message, 409)


def err_state_profile_conflict(message="Another ACTIVE profile with the same state_code exists"):
    return ApiError("ERR_STATE_PROFILE_CONFLICT", message, 409)


def err_state_profile_in_use(message="Retire blocked: live policies reference the profile"):
    return ApiError("ERR_STATE_PROFILE_IN_USE", message, 409)


def err_duplicate_policy_number(message="policy_number already in use"):
    return ApiError("ERR_DUPLICATE_POLICY_NUMBER", message, 409)


def err_interest_policy_mismatch(message="insured_interest_id belongs to a different policy than the case"):
    return ApiError("ERR_INTEREST_POLICY_MISMATCH", message, 422)


def err_report_period_still_open(message="Finalize attempted while current clock month is within report_period"):
    return ApiError("ERR_REPORT_PERIOD_STILL_OPEN", message, 409)


def err_stale_version(message="expected_policy_version does not match Policy.version at write time"):
    return ApiError("ERR_STALE_VERSION", message, 412)
