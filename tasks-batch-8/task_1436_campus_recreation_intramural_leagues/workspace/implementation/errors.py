"""Error catalog for the Campus Rec Intramurals API.

Every error carries the exact error_id and HTTP status from the scaffold/PRD.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- auth / request ---
def err_unauthenticated(msg="Authentication headers missing or role invalid"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Caller is not permitted to perform this operation"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_validation(msg="Request validation failed"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_invalid_state(msg="Resource is not in a state that permits this operation"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# --- member eligibility ---
def err_member_suspended(msg="Member is suspended"):
    return ApiError("ERR_MEMBER_SUSPENDED", 409, msg)


def err_membership_inactive(msg="Member holds no active membership"):
    return ApiError("ERR_MEMBERSHIP_INACTIVE", 409, msg)


def err_waiver_invalid(msg="No waiver signed for the current academic year"):
    return ApiError("ERR_WAIVER_INVALID", 422, msg)


def err_outstanding_fines(msg="Member has outstanding fines"):
    return ApiError("ERR_OUTSTANDING_FINES", 402, msg)


# --- league / team / roster ---
def err_league_not_accepting(msg="League is not accepting registrations"):
    return ApiError("ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS", 409, msg)


def err_too_few_teams(msg="League has fewer than min_teams teams"):
    return ApiError("ERR_TOO_FEW_TEAMS", 409, msg)


def err_league_not_ready(msg="League is not ready for season start"):
    return ApiError("ERR_LEAGUE_NOT_READY_FOR_SEASON", 409, msg)


def err_league_full(msg="League team capacity reached"):
    return ApiError("ERR_LEAGUE_FULL", 409, msg)


def err_division_not_found(msg="Division name not present in the league"):
    return ApiError("ERR_DIVISION_NOT_FOUND", 404, msg)


def err_division_full(msg="Division capacity reached"):
    return ApiError("ERR_DIVISION_FULL", 409, msg)


def err_division_skill_mismatch(msg="Team skill rating outside division bounds"):
    return ApiError("ERR_DIVISION_SKILL_MISMATCH", 422, msg)


def err_team_already_in_league(msg="Captain already captains a non-withdrawn team in this league"):
    return ApiError("ERR_TEAM_ALREADY_IN_LEAGUE", 409, msg)


def err_member_already_in_league(msg="Member already holds an active roster entry in this league"):
    return ApiError("ERR_MEMBER_ALREADY_IN_LEAGUE", 409, msg)


def err_roster_full(msg="Team roster is at the league maximum"):
    return ApiError("ERR_ROSTER_FULL", 422, msg)


def err_captain_removal(msg="The captain's roster entry can never be removed"):
    return ApiError("ERR_CAPTAIN_REMOVAL_FORBIDDEN", 422, msg)


def err_already_in_pool(msg="Member already has a pooled free-agent entry in this league"):
    return ApiError("ERR_ALREADY_IN_POOL", 409, msg)


def err_no_team_available(msg="No team is available for free-agent placement"):
    return ApiError("ERR_NO_TEAM_AVAILABLE", 409, msg)


# --- scheduling / temporal ---
def err_game_in_past(msg="start_at is before the logical current time"):
    return ApiError("ERR_GAME_IN_PAST", 422, msg)


def err_outside_hours(msg="Booking does not fit a single operating window"):
    return ApiError("ERR_FACILITY_OUTSIDE_HOURS", 422, msg)


def err_facility_closed(msg="Booking overlaps a facility closure"):
    return ApiError("ERR_FACILITY_CLOSED", 409, msg)


def err_double_booked(msg="Booking overlaps another scheduled booking at the facility"):
    return ApiError("ERR_FACILITY_DOUBLE_BOOKED", 409, msg)


def err_team_time_conflict(msg="A team already has a scheduled game overlapping this slot"):
    return ApiError("ERR_TEAM_TIME_CONFLICT", 409, msg)


def err_teams_not_in_same_division(msg="Teams do not share the same non-null division"):
    return ApiError("ERR_TEAMS_NOT_IN_SAME_DIVISION", 422, msg)


# --- game reporting / playoffs ---
def err_game_not_reportable(msg="Game is not in a reportable state or has not started"):
    return ApiError("ERR_GAME_NOT_REPORTABLE", 409, msg)


def err_duplicate_score_report(msg="This side has already submitted a score report"):
    return ApiError("ERR_DUPLICATE_SCORE_REPORT", 409, msg)


def err_tie_not_allowed(msg="Playoff games cannot end in a tie"):
    return ApiError("ERR_TIE_NOT_ALLOWED", 422, msg)


def err_forfeiting_team_invalid(msg="forfeiting_team_id must be the home or away team"):
    return ApiError("ERR_FORFEITING_TEAM_INVALID", 422, msg)


def err_playoffs_not_ready(msg="League still has unresolved games"):
    return ApiError("ERR_PLAYOFFS_NOT_READY", 409, msg)


def err_no_eligible_teams(msg="Fewer than two eligible teams league-wide"):
    return ApiError("ERR_NO_ELIGIBLE_TEAMS", 409, msg)


# --- officials / staff ---
def err_staff_not_official(msg="Staff member is not an OFFICIAL"):
    return ApiError("ERR_STAFF_NOT_OFFICIAL", 422, msg)


def err_staff_not_instructor(msg="Staff member is not an INSTRUCTOR"):
    return ApiError("ERR_STAFF_NOT_INSTRUCTOR", 422, msg)


def err_cert_too_low(msg="Official certification level below playoff requirement"):
    return ApiError("ERR_OFFICIAL_CERT_TOO_LOW", 422, msg)


def err_official_double_booked(msg="Assignment violates the official's travel buffer"):
    return ApiError("ERR_OFFICIAL_DOUBLE_BOOKED", 409, msg)


def err_assignment_limit(msg="Game already has two non-terminal officiating assignments"):
    return ApiError("ERR_ASSIGNMENT_LIMIT_REACHED", 422, msg)


def err_instructor_not_certified(msg="Instructor is not certified for this class type"):
    return ApiError("ERR_INSTRUCTOR_NOT_CERTIFIED", 422, msg)


# --- equipment / lockers / classes ---
def err_equipment_insufficient(msg="Requested quantity exceeds available pool quantity"):
    return ApiError("ERR_EQUIPMENT_INSUFFICIENT", 409, msg)


def err_locker_unavailable(msg="Locker is not AVAILABLE"):
    return ApiError("ERR_LOCKER_UNAVAILABLE", 409, msg)


def err_rental_exists(msg="Member already holds a rented locker"):
    return ApiError("ERR_RENTAL_EXISTS", 409, msg)


def err_class_already_registered(msg="Member already registered or waitlisted for this class"):
    return ApiError("ERR_CLASS_ALREADY_REGISTERED", 409, msg)


def err_class_time_conflict(msg="Member has a registration overlapping this class"):
    return ApiError("ERR_CLASS_TIME_CONFLICT", 409, msg)


def err_injury_game_mismatch(msg="Member holds no active roster entry on either team of that game"):
    return ApiError("ERR_INJURY_GAME_MISMATCH", 422, msg)
