"""Error taxonomy."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="X-User-Role header missing or unknown"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden_role(msg="Role not permitted to invoke this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def not_found(msg="Referenced resource does not exist within the parent scope"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Missing required field, invalid type, invalid enum value, or malformed id"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def stale_version(msg="Expected version does not match current parent version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def track_day_not_live(msg="TrackDay is CANCELLED or CLOSED; no forward progress allowed"):
    return ApiError("ERR_TRACK_DAY_NOT_LIVE", 409, msg)


def invalid_state(msg="State-machine precondition violated for the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def track_suspended(msg="TrackDay posture is SUSPENDED; forward-progress operation blocked"):
    return ApiError("ERR_TRACK_SUSPENDED", 409, msg)


def segregation_of_duties(msg="Segregation of duties violated"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 422, msg)


def driver_not_cleared(msg="Driver lacks signed waiver, passed inspection, approved booking, or captured payment"):
    return ApiError("ERR_DRIVER_NOT_CLEARED", 422, msg)


def coach_cert_insufficient(msg="Coach cert_level below requirement for the run_group_class"):
    return ApiError("ERR_COACH_CERT_INSUFFICIENT", 422, msg)


def coach_overloaded(msg="Coach already at maximum simultaneous bookings on this track day"):
    return ApiError("ERR_COACH_OVERLOADED", 409, msg)


def block_overlap(msg="RentalBlock interval overlaps an existing block on the same day"):
    return ApiError("ERR_BLOCK_OVERLAP", 409, msg)


def bay_occupied(msg="Garage bay already ACTIVE on this track day"):
    return ApiError("ERR_BAY_OCCUPIED", 409, msg)


def stall_occupied(msg="Paddock stall already ACTIVE on this track day"):
    return ApiError("ERR_STALL_OCCUPIED", 409, msg)


def group_size_exceeds_track_cap(msg="RentalBlock max_group_size exceeds the track's run_group_capacity"):
    return ApiError("ERR_GROUP_SIZE_EXCEEDS_TRACK_CAP", 422, msg)


def invalid_driver_count(msg="driver_count must be at least 1 and no more than the block's max_group_size"):
    return ApiError("ERR_INVALID_DRIVER_COUNT", 422, msg)


def block_full(msg="seats_available is insufficient for driver_count"):
    return ApiError("ERR_BLOCK_FULL", 409, msg)


def insurance_missing(msg="insurance_policy_ref is missing or empty"):
    return ApiError("ERR_INSURANCE_MISSING", 422, msg)
