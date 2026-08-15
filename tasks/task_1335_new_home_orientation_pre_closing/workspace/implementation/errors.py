"""Error type and constructors for the PRD §5 error catalogue (28 codes)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(message="X-User-Role header missing or not a declared role."):
    return ApiError("ERR_UNAUTHENTICATED", 401, message)


def err_forbidden(message="Role not permitted, or ownership check failed."):
    return ApiError("ERR_FORBIDDEN", 403, message)


def err_validation(message="Request failed schema validation."):
    return ApiError("ERR_VALIDATION", 400, message)


def err_not_found(message="Path identifier does not resolve."):
    return ApiError("ERR_NOT_FOUND", 404, message)


def err_referenced_entity_not_found(message="Body foreign key does not resolve."):
    return ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", 422, message)


def err_invalid_state(message="Entity is not in a valid from-state for this transition."):
    return ApiError("ERR_INVALID_STATE", 409, message)


def err_stale_version(message="Expected version does not match the current version."):
    return ApiError("ERR_STALE_VERSION", 412, message)


def err_self_verification(message="The conducting representative cannot decide attendee verification for their own appointment."):
    return ApiError("ERR_SELF_VERIFICATION_FORBIDDEN", 403, message)


def err_poa_document_required(message="POA_PROXY attendee requires proxy_name and poa_document_ref."):
    return ApiError("ERR_POA_DOCUMENT_REQUIRED", 422, message)


def err_attendee_identity(message="Attendee identity fields are inconsistent with attendee_type."):
    return ApiError("ERR_ATTENDEE_IDENTITY_INVALID", 422, message)


def err_outside_window(message="Orientation start is not within the scheduling window before closing."):
    return ApiError("ERR_OUTSIDE_SCHEDULING_WINDOW", 422, message)


def err_schedule_in_past(message="scheduled_start is not strictly after the current logical clock instant."):
    return ApiError("ERR_SCHEDULE_IN_PAST", 422, message)


def err_start_window(message="Start attempted outside the appointment start window."):
    return ApiError("ERR_APPOINTMENT_START_WINDOW", 409, message)


def err_survey_expired(message="The survey submission window has closed."):
    return ApiError("ERR_SURVEY_EXPIRED", 409, message)


def err_visit_too_early(message="Visit completion attempted before its scheduled_start."):
    return ApiError("ERR_VISIT_TOO_EARLY", 409, message)


def err_open_appointment_exists(message="The home already has an open orientation appointment."):
    return ApiError("ERR_OPEN_APPOINTMENT_EXISTS", 409, message)


def err_rep_schedule_conflict(message="Appointment collides with the representative's buffered schedule."):
    return ApiError("ERR_REP_SCHEDULE_CONFLICT", 409, message)


def err_visit_overlap(message="Visit collides with an existing scheduled visit of the representative."):
    return ApiError("ERR_VISIT_OVERLAP", 409, message)


def err_daily_capacity(message="Visit would exceed the representative's daily visit capacity."):
    return ApiError("ERR_DAILY_CAPACITY_EXCEEDED", 409, message)


def err_reschedule_limit(message="The appointment has already reached the reschedule limit of 3."):
    return ApiError("ERR_RESCHEDULE_LIMIT_REACHED", 409, message)


def err_checklist_incomplete(message="A required checklist item is not demonstrated or an item is still pending."):
    return ApiError("ERR_CHECKLIST_INCOMPLETE", 409, message)


def err_attendee_requirement(message="No verified attendee covers the primary buyer."):
    return ApiError("ERR_ATTENDEE_REQUIREMENT_UNMET", 409, message)


def err_photo_evidence(message="COSMETIC classification requires photo_evidence_ref for this community."):
    return ApiError("ERR_PHOTO_EVIDENCE_REQUIRED", 422, message)


def err_withdraw_not_allowed(message="Only unclassified or cosmetic-classified items may be withdrawn."):
    return ApiError("ERR_WITHDRAW_NOT_ALLOWED", 409, message)


def err_rep_inactive(message="The named representative is inactive."):
    return ApiError("ERR_REP_INACTIVE", 409, message)


def err_duplicate_email(message="The email address is already registered."):
    return ApiError("ERR_DUPLICATE_EMAIL", 409, message)


def err_no_releasable(message="No releasable amount: no unreleased signed-off items and no flush applies."):
    return ApiError("ERR_NO_RELEASABLE_AMOUNT", 409, message)


def err_funding_mismatch(message="funded_holdback_cents does not equal the computed final holdback."):
    return ApiError("ERR_HOLDBACK_FUNDING_MISMATCH", 422, message)
