"""Error classes with the catalog's exact error_id values and HTTP statuses."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized_role(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def study_not_found(msg="Study not found"):
    return ApiError("ERR_STUDY_NOT_FOUND", 404, msg)


def site_not_found(msg="Site not found"):
    return ApiError("ERR_SITE_NOT_FOUND", 404, msg)


def kit_not_found(msg="Kit not found"):
    return ApiError("ERR_KIT_NOT_FOUND", 404, msg)


def subject_not_found(msg="Subject not found"):
    return ApiError("ERR_SUBJECT_NOT_FOUND", 404, msg)


def not_found(msg="Referenced entity not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="Invalid state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def study_not_active(msg="Study is not ACTIVE"):
    return ApiError("ERR_STUDY_NOT_ACTIVE", 409, msg)


def site_not_active(msg="Site is not ACTIVE"):
    return ApiError("ERR_SITE_NOT_ACTIVE", 409, msg)


def kit_not_releasable(msg="Kit is not in QUARANTINED_RECEIPT"):
    return ApiError("ERR_KIT_NOT_RELEASABLE", 409, msg)


def kit_not_dispensable(msg="Kit is not ALLOCATED to this subject"):
    return ApiError("ERR_KIT_NOT_DISPENSABLE", 409, msg)


def subject_not_randomizable(msg="Subject is not in SCREENING"):
    return ApiError("ERR_SUBJECT_NOT_RANDOMIZABLE", 409, msg)


def subject_not_randomized(msg="Subject is not RANDOMIZED"):
    return ApiError("ERR_SUBJECT_NOT_RANDOMIZED", 409, msg)


def already_terminal(msg="Entity is in a terminal state"):
    return ApiError("ERR_ALREADY_TERMINAL", 409, msg)


def excursion_already_resolved(msg="Excursion is not OPEN"):
    return ApiError("ERR_EXCURSION_ALREADY_RESOLVED", 409, msg)


def stale_version(msg="expected_study_version does not match current study version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def lot_expired(msg="Lot has expired"):
    return ApiError("ERR_LOT_EXPIRED", 422, msg)


def kit_quarantined_excursion(msg="Kit is in QUARANTINED_EXCURSION"):
    return ApiError("ERR_KIT_QUARANTINED_EXCURSION", 422, msg)


def lot_stability_exhausted(msg="Lot stability budget exhausted"):
    return ApiError("ERR_LOT_STABILITY_EXHAUSTED", 422, msg)


def dose_exceeds(msg="Dose exceeds protocol maximum"):
    return ApiError("ERR_DOSE_EXCEEDS_PROTOCOL_MAX", 422, msg)


def study_open_label(msg="Study is OPEN_LABEL; nothing to unblind"):
    return ApiError("ERR_STUDY_OPEN_LABEL", 422, msg)


def visit_window_violation(msg="Dispense outside protocol visit window"):
    return ApiError("ERR_VISIT_WINDOW_VIOLATION", 422, msg)


def visit_out_of_sequence(msg="visit_number is out of sequence"):
    return ApiError("ERR_VISIT_OUT_OF_SEQUENCE", 422, msg)


def outside_visit_window(msg="Logical clock outside scheduled visit window"):
    return ApiError("ERR_OUTSIDE_VISIT_WINDOW", 422, msg)


def monitor_visit_overlap(msg="Visit window overlaps an existing visit at this site"):
    return ApiError("ERR_MONITOR_VISIT_OVERLAP", 409, msg)


def destruction_window_conflict(msg="Destruction facility window conflicts at this site"):
    return ApiError("ERR_DESTRUCTION_WINDOW_CONFLICT", 409, msg)


def no_randomization_slot(msg="No UNASSIGNED slot for this stratum"):
    return ApiError("ERR_NO_RANDOMIZATION_SLOT", 422, msg)


def slot_kit_unavailable(msg="Slot's kit is not AVAILABLE at the subject's site"):
    return ApiError("ERR_SLOT_KIT_UNAVAILABLE", 422, msg)


def duplicate_protocol_number(msg="protocol_number already exists"):
    return ApiError("ERR_DUPLICATE_PROTOCOL_NUMBER", 409, msg)


def duplicate_kit_number(msg="kit_number duplicated within study or payload"):
    return ApiError("ERR_DUPLICATE_KIT_NUMBER", 409, msg)


def rescreen_limit(msg="Rescreen limit exceeded"):
    return ApiError("ERR_RESCREEN_LIMIT_EXCEEDED", 422, msg)


def segregation(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 422, msg)


def quantity_mismatch(msg="Quantity mismatch"):
    return ApiError("ERR_QUANTITY_MISMATCH", 422, msg)


def unverified_return_pending(msg="Unverified return pending at site"):
    return ApiError("ERR_UNVERIFIED_RETURN_PENDING", 422, msg)


def count_incomplete(msg="Counts do not cover every on-hand kit exactly once"):
    return ApiError("ERR_COUNT_INCOMPLETE", 422, msg)


def no_approved_fee_schedule(msg="No APPROVED fee schedule for the study"):
    return ApiError("ERR_NO_APPROVED_FEE_SCHEDULE", 422, msg)


def active_dispensing_exists(msg="Subject has an ACTIVE dispensing record"):
    return ApiError("ERR_ACTIVE_DISPENSING_EXISTS", 422, msg)
