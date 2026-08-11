"""Error classes carrying scaffold error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_role_forbidden(msg="Role not authorized for this operation"):
    return ApiError("ERR_ROLE_FORBIDDEN", msg, 403)


def err_sod(msg="Segregation-of-duties: same user cannot settle an agreement they created"):
    return ApiError("ERR_SOD_VIOLATION", msg, 403)


def err_not_found(msg="Resource not found at the specified path"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_referential(msg="Foreign key references a non-existent entity"):
    return ApiError("ERR_REFERENTIAL_INTEGRITY", msg, 422)


def err_screen_theatre_mismatch(msg="screen_id's theatre_id does not match request theatre_id"):
    return ApiError("ERR_SCREEN_THEATRE_MISMATCH", msg, 422)


def err_stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_invalid_state(msg="Resource is in wrong state for requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_distributor_frozen(msg="Distributor is FROZEN; new bookings blocked while a dispute is open"):
    return ApiError("ERR_DISTRIBUTOR_FROZEN", msg, 409)


def err_film_not_bookable(msg="Film.lifecycle_status is not in {PRE_RELEASE, IN_RELEASE, HOLDOVER_PHASE}"):
    return ApiError("ERR_FILM_NOT_BOOKABLE", msg, 409)


def err_theatre_inactive(msg="Theatre.status is not ACTIVE"):
    return ApiError("ERR_THEATRE_INACTIVE", msg, 409)


def err_screen_unavailable(msg="Screen already committed to another booking or in MAINTENANCE"):
    return ApiError("ERR_SCREEN_UNAVAILABLE", msg, 409)


def err_zone_conflict(msg="Zone clearance conflict"):
    return ApiError("ERR_ZONE_CLEARANCE_CONFLICT", msg, 409)


def err_kdm_conflict(msg="Proposed KDM window overlaps another ISSUED/LIVE KDM on the same screen"):
    return ApiError("ERR_KDM_WINDOW_CONFLICT", msg, 409)


def err_print_not_ready(msg="BookingAgreement.print_status not in prerequisite state"):
    return ApiError("ERR_PRINT_NOT_READY", msg, 409)


def err_invalid_rental_terms(msg="week_one_rental_pct outside [0.00, 0.95] OR floor_pct > week_one_rental_pct"):
    return ApiError("ERR_INVALID_RENTAL_TERMS", msg, 422)


def err_coop_budget(msg="Marketing commit would push market.coop_committed_cents over 4x weekly budget"):
    return ApiError("ERR_COOP_BUDGET_EXCEEDED", msg, 409)


def err_wide_gate(msg="WIDE release requires screens_committed >= min_screens_for_wide"):
    return ApiError("ERR_WIDE_GATE_NOT_MET", msg, 409)


def err_ancillary_too_early(msg="AncillaryWindow.scheduled_start_utc < Film.theatrical_window_end"):
    return ApiError("ERR_ANCILLARY_TOO_EARLY", msg, 422)


def err_report_outside_window(msg="BoxOfficeReport.report_date is not within current or prior week_epoch"):
    return ApiError("ERR_REPORT_OUTSIDE_WINDOW", msg, 422)


def err_holdover_not_eligible(msg="weeks_played < min_weeks_committed"):
    return ApiError("ERR_HOLDOVER_NOT_ELIGIBLE", msg, 409)


def err_invalid_request(msg="Malformed request payload; missing required field; invalid enum value"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)
