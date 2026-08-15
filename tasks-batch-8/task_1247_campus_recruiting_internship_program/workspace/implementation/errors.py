"""Custom error classes carrying error_id, message, http_status."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or unrecognized X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not allowed on the endpoint, or ownership check failed"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="A path resource id does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_validation(msg="Missing required field, invalid type, invalid enum member, or range violation"):
    return ApiError("ERR_VALIDATION", msg, 400)


def err_stale_school_target_version(msg="expected_school_target_version does not match the SchoolTarget's current version"):
    return ApiError("ERR_STALE_SCHOOL_TARGET_VERSION", msg, 412)


def err_stale_offer_version(msg="expected_offer_version does not match the Offer's current version"):
    return ApiError("ERR_STALE_OFFER_VERSION", msg, 412)


def err_season_posture_forbidden(msg="Season status does not permit this operation"):
    return ApiError("ERR_SEASON_POSTURE_FORBIDDEN", msg, 409)


def err_season_advance_blocked(msg="Season advance precondition failed"):
    return ApiError("ERR_SEASON_ADVANCE_BLOCKED", msg, 409)


def err_season_close_blocked(msg="Season close attempted while ACTIVE ProjectAssignments remain"):
    return ApiError("ERR_SEASON_CLOSE_BLOCKED", msg, 409)


def err_application_state_forbidden(msg="Application status does not permit the requested transition"):
    return ApiError("ERR_APPLICATION_STATE_FORBIDDEN", msg, 409)


def err_offer_state_forbidden(msg="Offer status does not permit the requested transition"):
    return ApiError("ERR_OFFER_STATE_FORBIDDEN", msg, 409)


def err_day_state_forbidden(msg="InterviewDay status does not permit the operation"):
    return ApiError("ERR_DAY_STATE_FORBIDDEN", msg, 409)


def err_slot_state_forbidden(msg="InterviewSlot is not BOOKED"):
    return ApiError("ERR_SLOT_STATE_FORBIDDEN", msg, 409)


def err_event_state_forbidden(msg="CampusEvent is not SCHEDULED"):
    return ApiError("ERR_EVENT_STATE_FORBIDDEN", msg, 409)


def err_disbursement_state_forbidden(msg="StipendDisbursement is not RESERVED"):
    return ApiError("ERR_DISBURSEMENT_STATE_FORBIDDEN", msg, 409)


def err_project_state_forbidden(msg="InternProject is not OPEN"):
    return ApiError("ERR_PROJECT_STATE_FORBIDDEN", msg, 409)


def err_assignment_state_forbidden(msg="ProjectAssignment status or return-offer fields do not permit the operation"):
    return ApiError("ERR_ASSIGNMENT_STATE_FORBIDDEN", msg, 409)


def err_evaluator_conflict_of_interest(msg="Evaluator's alma_mater_school_name equals the applicant's school name"):
    return ApiError("ERR_EVALUATOR_CONFLICT_OF_INTEREST", msg, 422)


def err_evaluator_not_calibrated(msg="CORE-tier school's candidate assigned to an uncalibrated evaluator"):
    return ApiError("ERR_EVALUATOR_NOT_CALIBRATED", msg, 422)


def err_mentor_conflict_of_interest(msg="Proposed mentor previously submitted an evaluation for this application"):
    return ApiError("ERR_MENTOR_CONFLICT_OF_INTEREST", msg, 422)


def err_capability_missing(msg="Employee lacks the required capability flag"):
    return ApiError("ERR_CAPABILITY_MISSING", msg, 422)


def err_application_window_closed(msg="Application submitted outside the application window"):
    return ApiError("ERR_APPLICATION_WINDOW_CLOSED", msg, 422)


def err_day_outside_window(msg="InterviewDay window not contained in the season interview window"):
    return ApiError("ERR_DAY_OUTSIDE_WINDOW", msg, 422)


def err_slot_outside_day_window(msg="Slot interval not contained in the interview day's window"):
    return ApiError("ERR_SLOT_OUTSIDE_DAY_WINDOW", msg, 422)


def err_offer_window_closed(msg="Offer extend attempted outside the offer window"):
    return ApiError("ERR_OFFER_WINDOW_CLOSED", msg, 422)


def err_offer_expired(msg="Accept attempted after deadline_at; offer flipped to EXPIRED"):
    return ApiError("ERR_OFFER_EXPIRED", msg, 422)


def err_offer_not_yet_expired(msg="Expire sweep attempted while now <= deadline_at"):
    return ApiError("ERR_OFFER_NOT_YET_EXPIRED", msg, 422)


def err_mid_evaluation_required(msg="FINAL intern evaluation submitted before any MID evaluation exists"):
    return ApiError("ERR_MID_EVALUATION_REQUIRED", msg, 422)


def err_final_evaluation_required(msg="Assignment completion attempted before any FINAL intern evaluation exists"):
    return ApiError("ERR_FINAL_EVALUATION_REQUIRED", msg, 422)


def err_duplicate_email(msg="Candidate email already registered"):
    return ApiError("ERR_DUPLICATE_EMAIL", msg, 409)


def err_duplicate_application(msg="Candidate already has an application in this season"):
    return ApiError("ERR_DUPLICATE_APPLICATION", msg, 409)


def err_school_application_cap_reached(msg="School's non-terminal application count has reached application_cap"):
    return ApiError("ERR_SCHOOL_APPLICATION_CAP_REACHED", msg, 422)


def err_school_dropped(msg="Referenced SchoolTarget has status DROPPED"):
    return ApiError("ERR_SCHOOL_DROPPED", msg, 422)


def err_screening_threshold_not_met(msg="SHORTLIST decision with screening_score_final below the season threshold"):
    return ApiError("ERR_SCREENING_THRESHOLD_NOT_MET", msg, 422)


def err_event_time_overlap(msg="Campus event interval intersects another event of the same school"):
    return ApiError("ERR_EVENT_TIME_OVERLAP", msg, 409)


def err_candidate_schedule_conflict(msg="Candidate already holds a BOOKED slot overlapping the requested interval"):
    return ApiError("ERR_CANDIDATE_SCHEDULE_CONFLICT", msg, 409)


def err_evaluator_schedule_conflict(msg="Evaluator would have less than the 15-minute buffer between slots on the same day"):
    return ApiError("ERR_EVALUATOR_SCHEDULE_CONFLICT", msg, 409)


def err_day_at_capacity(msg="InterviewDay.booked_count >= capacity or evaluator daily_slot_limit reached"):
    return ApiError("ERR_DAY_AT_CAPACITY", msg, 422)


def err_offer_already_exists(msg="An Offer already exists for this application"):
    return ApiError("ERR_OFFER_ALREADY_EXISTS", msg, 409)


def err_extension_cap_exceeded(msg="extension_hours_granted + additional_hours exceeds season.max_extension_hours"):
    return ApiError("ERR_EXTENSION_CAP_EXCEEDED", msg, 422)


def err_project_at_capacity(msg="InternProject.assigned_count >= capacity"):
    return ApiError("ERR_PROJECT_AT_CAPACITY", msg, 422)


def err_mentor_at_capacity(msg="Mentor's assigned_intern_count >= max_interns"):
    return ApiError("ERR_MENTOR_AT_CAPACITY", msg, 422)


def err_assignment_exists(msg="Application already has a ProjectAssignment"):
    return ApiError("ERR_ASSIGNMENT_EXISTS", msg, 409)


def err_evaluation_already_submitted(msg="An InternEvaluation of this eval_type already exists for the assignment"):
    return ApiError("ERR_EVALUATION_ALREADY_SUBMITTED", msg, 409)


def err_stipend_budget_exceeded(msg="Stipend budget would be exceeded"):
    return ApiError("ERR_STIPEND_BUDGET_EXCEEDED", msg, 422)
