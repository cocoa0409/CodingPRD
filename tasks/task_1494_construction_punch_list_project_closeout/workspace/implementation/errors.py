"""Error type carrying the scaffold-declared error_id / http_status (SCAFFOLD 1.6,
PRD section 5). Every constructor's id and status come from the error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role is not in the endpoint's allowed roles"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_responsible_party(msg="Caller is not the responsible party for this trade"):
    return ApiError("ERR_NOT_RESPONSIBLE_PARTY", 403, msg)


def segregation_of_duties(msg="The user who marked the item ready may not verify it"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def verification_escalated(msg="Item rejected at least twice requires GCProjectManager verification"):
    return ApiError("ERR_VERIFICATION_ESCALATED", 403, msg)


def invalid_request(msg="Request body is missing a required field or is malformed"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def not_found(msg="A referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg="The current state does not permit the requested operation"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def project_not_closed(msg="Warranty cases may only be reported against a CLOSED project"):
    return ApiError("ERR_PROJECT_NOT_CLOSED", 409, msg)


def open_life_safety_items(msg="Blocking LIFE_SAFETY punch items exist"):
    return ApiError("ERR_OPEN_LIFE_SAFETY_ITEMS", 409, msg)


def open_major_items(msg="Blocking MAJOR punch items exist"):
    return ApiError("ERR_OPEN_MAJOR_ITEMS", 409, msg)


def too_many_open_minor_items(msg="Open MINOR punch items exceed the allowance of 5"):
    return ApiError("ERR_TOO_MANY_OPEN_MINOR_ITEMS", 409, msg)


def walk_incomplete(msg="A trade package has no COMPLETED walk"):
    return ApiError("ERR_WALK_INCOMPLETE", 409, msg)


def no_trade_packages(msg="The project has no trade packages"):
    return ApiError("ERR_NO_TRADE_PACKAGES", 409, msg)


def walk_overlap(msg="The walk window overlaps another walk for the same lead inspector"):
    return ApiError("ERR_WALK_OVERLAP", 409, msg)


def walk_not_started(msg="The walk's scheduled window has not started per the logical clock"):
    return ApiError("ERR_WALK_NOT_STARTED", 409, msg)


def scheduled_in_past(msg="scheduled_start is before the current logical clock"):
    return ApiError("ERR_SCHEDULED_IN_PAST", 409, msg)


def session_room_conflict(msg="The session violates the 30-minute room turnover buffer"):
    return ApiError("ERR_SESSION_ROOM_CONFLICT", 409, msg)


def session_not_started(msg="The session's scheduled window has not started per the logical clock"):
    return ApiError("ERR_SESSION_NOT_STARTED", 409, msg)


def no_attendees(msg="attendee_count must be at least 1"):
    return ApiError("ERR_NO_ATTENDEES", 409, msg)


def reschedule_limit(msg="The session has already been rescheduled twice"):
    return ApiError("ERR_RESCHEDULE_LIMIT", 409, msg)


def duplicate_trade(msg="A trade package with this trade_name already exists for the project"):
    return ApiError("ERR_DUPLICATE_TRADE", 409, msg)


def doc_already_pending(msg="A SUBMITTED document already exists for this trade and doc_type"):
    return ApiError("ERR_DOC_ALREADY_PENDING", 409, msg)


def doc_type_already_satisfied(msg="An APPROVED document already exists for this trade and doc_type"):
    return ApiError("ERR_DOC_TYPE_ALREADY_SATISFIED", 409, msg)


def waiver_not_acceptable_state(msg="The waiver type may not be accepted in the current project phase"):
    return ApiError("ERR_WAIVER_NOT_ACCEPTABLE_STATE", 409, msg)


def waiver_already_accepted(msg="The lien waiver has already been accepted"):
    return ApiError("ERR_WAIVER_ALREADY_ACCEPTED", 409, msg)


def occupancy_not_registered(msg="Beneficial occupancy has not been registered"):
    return ApiError("ERR_OCCUPANCY_NOT_REGISTERED", 409, msg)


def occupancy_already_registered(msg="Beneficial occupancy has already been registered"):
    return ApiError("ERR_OCCUPANCY_ALREADY_REGISTERED", 409, msg)


def occupancy_before_sc(msg="occupancy_date is earlier than substantial_completion_date"):
    return ApiError("ERR_OCCUPANCY_BEFORE_SC", 422, msg)


def release_kind_already_used(msg="A release of this kind already exists in REQUESTED or PAID status"):
    return ApiError("ERR_RELEASE_KIND_ALREADY_USED", 409, msg)


def release_amount_zero(msg="The computed REDUCTION amount is zero"):
    return ApiError("ERR_RELEASE_AMOUNT_ZERO", 409, msg)


def final_release_not_paid(msg="No PAID FINAL retainage release exists for the project"):
    return ApiError("ERR_FINAL_RELEASE_NOT_PAID", 409, msg)


def trade_not_in_project(msg="trade_package_id does not belong to the referenced project"):
    return ApiError("ERR_TRADE_NOT_IN_PROJECT", 422, msg)


def walk_not_in_project(msg="punch_walk_id does not belong to the referenced project"):
    return ApiError("ERR_WALK_NOT_IN_PROJECT", 422, msg)


def warranty_expired(msg="The warranty window has expired"):
    return ApiError("ERR_WARRANTY_EXPIRED", 422, msg)
