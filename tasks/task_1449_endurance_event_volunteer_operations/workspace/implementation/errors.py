"""Error classes carrying scaffold error_id + http status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message, http_status):
    return ApiError(error_id, message, http_status)


# --- Auth ---
def missing_or_invalid_user_context():
    return err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
               "X-User-ID and X-User-Role headers are required and the role must be declared.", 400)


def forbidden_role():
    return err("ERR_FORBIDDEN_ROLE", "The caller's role is not authorized for this endpoint.", 403)


def not_resource_owner():
    return err("ERR_NOT_RESOURCE_OWNER", "The caller does not own the target resource.", 403)


def invalid_request(message="Invalid request."):
    return err("ERR_INVALID_REQUEST", message, 400)


# --- Not found family ---
def event_not_found():
    return err("ERR_EVENT_NOT_FOUND", "Event does not exist.", 404)


def segment_not_found():
    return err("ERR_SEGMENT_NOT_FOUND", "Course segment does not exist.", 404)


def role_entry_not_found():
    return err("ERR_ROLE_ENTRY_NOT_FOUND", "Role catalog entry does not exist.", 404)


def shift_not_found():
    return err("ERR_SHIFT_NOT_FOUND", "Shift does not exist.", 404)


def group_not_found():
    return err("ERR_GROUP_NOT_FOUND", "Fundraising group does not exist.", 404)


def volunteer_not_found():
    return err("ERR_VOLUNTEER_NOT_FOUND", "Volunteer does not exist.", 404)


def training_record_not_found():
    return err("ERR_TRAINING_RECORD_NOT_FOUND", "Training record does not exist.", 404)


def signup_not_found():
    return err("ERR_SIGNUP_NOT_FOUND", "Signup does not exist.", 404)


def inventory_not_found():
    return err("ERR_INVENTORY_NOT_FOUND", "Supply inventory does not exist.", 404)


def distribution_not_found():
    return err("ERR_DISTRIBUTION_NOT_FOUND", "Distribution record does not exist.", 404)


def hour_log_not_found():
    return err("ERR_HOUR_LOG_NOT_FOUND", "Hour log does not exist.", 404)


def debrief_not_found():
    return err("ERR_DEBRIEF_NOT_FOUND", "Debrief report does not exist.", 404)


def adjustment_not_found():
    return err("ERR_ADJUSTMENT_NOT_FOUND", "Role adjustment does not exist.", 404)


# --- 409 state family ---
def invalid_event_state(msg="Operation not allowed from the event's current status."):
    return err("ERR_INVALID_EVENT_STATE", msg, 409)


def event_not_published():
    return err("ERR_EVENT_NOT_PUBLISHED", "Operation requires the event to be PUBLISHED.", 409)


def event_readiness_incomplete():
    return err("ERR_EVENT_READINESS_INCOMPLETE",
               "Publish requires at least one ACTIVE role entry, one course segment, and one shift.", 409)


def event_not_yet_started():
    return err("ERR_EVENT_NOT_YET_STARTED", "The event has not yet started.", 409)


def event_not_yet_ended():
    return err("ERR_EVENT_NOT_YET_ENDED", "The event has not yet ended.", 409)


def signups_still_on_course():
    return err("ERR_SIGNUPS_STILL_ON_COURSE", "Signups remain CHECKED_IN on the course.", 409)


def event_close_blocked():
    return err("ERR_EVENT_CLOSE_BLOCKED", "Event close is blocked by unresolved resources.", 409)


def shift_not_open():
    return err("ERR_SHIFT_NOT_OPEN", "Shift is not OPEN or FULL.", 409)


def shift_capacity_reached():
    return err("ERR_SHIFT_CAPACITY_REACHED", "Shift confirmed_count has reached required_headcount.", 409)


def shift_has_unresolved_signups():
    return err("ERR_SHIFT_HAS_UNRESOLVED_SIGNUPS",
               "Shift still has CONFIRMED or CHECKED_IN signups.", 409)


def shift_time_overlap():
    return err("ERR_SHIFT_TIME_OVERLAP", "Volunteer holds an overlapping APPROVED/CONFIRMED signup.", 409)


def segment_mile_overlap():
    return err("ERR_SEGMENT_MILE_OVERLAP",
               "Mile range overlaps an existing segment of the same event.", 409)


def duplicate_signup():
    return err("ERR_DUPLICATE_SIGNUP", "Volunteer already holds an active signup on this shift.", 409)


def duplicate_training_record():
    return err("ERR_DUPLICATE_TRAINING_RECORD",
               "A training record already exists for this volunteer and module.", 409)


def captain_slot_taken():
    return err("ERR_CAPTAIN_SLOT_TAKEN", "Shift already has a captain.", 409)


def credential_already_issued():
    return err("ERR_CREDENTIAL_ALREADY_ISSUED",
               "Signup already has an ISSUED credential.", 409)


def signup_not_approvable():
    return err("ERR_SIGNUP_NOT_APPROVABLE", "Approve requires signup status REQUESTED.", 409)


def signup_not_confirmable():
    return err("ERR_SIGNUP_NOT_CONFIRMABLE", "Confirm requires signup status APPROVED.", 409)


def signup_not_cancellable():
    return err("ERR_SIGNUP_NOT_CANCELLABLE", "Signup cannot be cancelled from its current status.", 409)


def signup_not_checkinable():
    return err("ERR_SIGNUP_NOT_CHECKINABLE", "Check-in requires signup status CONFIRMED.", 409)


def signup_not_checked_outable():
    return err("ERR_SIGNUP_NOT_CHECKED_OUTABLE", "Check-out requires signup status CHECKED_IN.", 409)


def signup_not_no_showable():
    return err("ERR_SIGNUP_NOT_NO_SHOWABLE", "Mark-no-show requires signup status CONFIRMED.", 409)


def signup_not_checked_in():
    return err("ERR_SIGNUP_NOT_CHECKED_IN", "Distribution requires signup status CHECKED_IN.", 409)


def volunteer_not_eligible():
    return err("ERR_VOLUNTEER_NOT_ELIGIBLE", "Volunteer must be ELIGIBLE.", 409)


def volunteer_not_screenable():
    return err("ERR_VOLUNTEER_NOT_SCREENABLE", "Screen requires volunteer status REGISTERED.", 409)


def volunteer_not_suspended():
    return err("ERR_VOLUNTEER_NOT_SUSPENDED", "Reinstate requires volunteer status SUSPENDED.", 409)


def training_invalid_state():
    return err("ERR_TRAINING_INVALID_STATE", "Training record state does not allow this transition.", 409)


def role_entry_invalid_state():
    return err("ERR_ROLE_ENTRY_INVALID_STATE", "Role entry state does not allow this transition.", 409)


def role_entry_not_active():
    return err("ERR_ROLE_ENTRY_NOT_ACTIVE", "Role entry is not ACTIVE.", 409)


def role_in_use():
    return err("ERR_ROLE_IN_USE", "Role has non-terminal signups on its shifts.", 409)


def group_invalid_state():
    return err("ERR_GROUP_INVALID_STATE", "Group state does not allow this transition.", 409)


def group_suspended():
    return err("ERR_GROUP_SUSPENDED", "Fundraising group is SUSPENDED.", 409)


def hour_log_invalid_state():
    return err("ERR_HOUR_LOG_INVALID_STATE", "Hour log state does not allow this transition.", 409)


def distribution_invalid_state():
    return err("ERR_DISTRIBUTION_INVALID_STATE", "Distribution record state does not allow this transition.", 409)


def debrief_invalid_state():
    return err("ERR_DEBRIEF_INVALID_STATE", "Debrief report state does not allow this transition.", 409)


def debrief_not_acknowledged():
    return err("ERR_DEBRIEF_NOT_ACKNOWLEDGED", "The cited debrief report is not ACKNOWLEDGED.", 409)


def adjustment_invalid_state():
    return err("ERR_ADJUSTMENT_INVALID_STATE", "Role adjustment state does not allow this transition.", 409)


# --- 422 business family ---
def min_age_not_met():
    return err("ERR_MIN_AGE_NOT_MET", "Minimum age requirement is not met.", 422)


def required_skill_missing():
    return err("ERR_REQUIRED_SKILL_MISSING", "Volunteer lacks the role's required skill.", 422)


def training_not_current():
    return err("ERR_TRAINING_NOT_CURRENT", "Required training is not current.", 422)


def signup_window_closed():
    return err("ERR_SIGNUP_WINDOW_CLOSED", "The signup window is closed.", 422)


def early_access_restricted():
    return err("ERR_EARLY_ACCESS_RESTRICTED",
               "Early-access window requires a returning volunteer.", 422)


def checkin_window_invalid():
    return err("ERR_CHECKIN_WINDOW_INVALID", "Check-in is outside the allowed window.", 422)


def confirm_deadline_passed():
    return err("ERR_CONFIRM_DEADLINE_PASSED", "The confirmation deadline has passed.", 422)


def no_show_grace_not_passed():
    return err("ERR_NO_SHOW_GRACE_NOT_PASSED", "The no-show grace period has not passed.", 422)


def out_of_stock():
    return err("ERR_OUT_OF_STOCK", "Supply inventory is out of stock.", 422)


# --- 412 OCC ---
def stale_version():
    return err("ERR_STALE_VERSION", "Expected version does not match the current version.", 412)
