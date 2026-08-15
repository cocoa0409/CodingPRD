"""Error catalog: error ids and HTTP statuses, read from SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- catalog -------------------------------------------------------------
def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Required field missing, wrong type, or invalid enum value"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Current state does not permit the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="expected_facility_version does not match current facility version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_facility_closed(msg="Facility is closed for this operation"):
    return ApiError("ERR_FACILITY_CLOSED", 409, msg)


def err_facility_at_capacity(msg="Facility bather capacity reached"):
    return ApiError("ERR_FACILITY_AT_CAPACITY", 409, msg)


def err_holder_banned(msg="Pass holder is currently banned"):
    return ApiError("ERR_HOLDER_BANNED", 409, msg)


def err_guard_not_certified(msg="Lifeguard certification is not ACTIVE"):
    return ApiError("ERR_GUARD_NOT_CERTIFIED", 409, msg)


def err_rental_overlap(msg="Rental window overlaps another approved or checked-in rental"):
    return ApiError("ERR_RENTAL_OVERLAP", 409, msg)


def err_rental_capacity(msg="Rental exceeds facility capacity or overlaps reserved lanes"):
    return ApiError("ERR_RENTAL_CAPACITY", 409, msg)


def err_lane_capacity(msg="Insufficient free lap lanes for the requested window"):
    return ApiError("ERR_LANE_CAPACITY_EXCEEDED", 409, msg)


def err_session_outside_season(msg="Lesson session window lies outside its season"):
    return ApiError("ERR_SESSION_OUTSIDE_SEASON", 422, msg)


def err_admission_date(msg="admission_date is not today or season not PUBLISHED on that date"):
    return ApiError("ERR_ADMISSION_DATE_INVALID", 422, msg)


def err_shift_window(msg="Shift window is malformed or outside the booking horizon"):
    return ApiError("ERR_SHIFT_WINDOW_INVALID", 422, msg)


def err_prerequisite(msg="Enrollment prerequisite or age minimum not met"):
    return ApiError("ERR_PREREQUISITE_NOT_MET", 422, msg)


def err_season_overlap(msg="Season pricing invalid or window overlaps another PUBLISHED season"):
    return ApiError("ERR_SEASON_OVERLAP", 409, msg)


def err_chemistry_input(msg="Chemistry reading outside plausible instrument bounds"):
    return ApiError("ERR_CHEMISTRY_INPUT_INVALID", 422, msg)


def err_reopen_criteria(msg="Reopen criteria not met"):
    return ApiError("ERR_REOPEN_CRITERIA_NOT_MET", 409, msg)


def err_pass_not_valid(msg="Season pass is not ACTIVE or does not belong to the current season"):
    return ApiError("ERR_PASS_NOT_VALID", 409, msg)


def err_already_checked_in(msg="Record is already checked in / entered"):
    return ApiError("ERR_ALREADY_CHECKED_IN", 409, msg)
