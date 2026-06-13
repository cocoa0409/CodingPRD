"""Error catalog and the ApiError exception.

Every (error_id, http_status) pair is taken verbatim from PRD §5 and
SCAFFOLD §1.6. No error string is invented here.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth ---
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)

# --- existence ---
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)

# --- request validity ---
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)

# --- state ---
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_LEAGUE_NOT_OPEN = ("ERR_LEAGUE_NOT_OPEN", 409)
ERR_GAME_NOT_OPEN = ("ERR_GAME_NOT_OPEN", 409)
ERR_GAME_LOCKED = ("ERR_GAME_LOCKED", 409)
ERR_GAME_NOT_STARTED = ("ERR_GAME_NOT_STARTED", 409)
ERR_CREW_NOT_PROVISIONED = ("ERR_CREW_NOT_PROVISIONED", 409)
ERR_CREW_INCOMPLETE = ("ERR_CREW_INCOMPLETE", 409)
ERR_SLOT_NOT_VACANT = ("ERR_SLOT_NOT_VACANT", 409)
ERR_OFFICIAL_SUSPENDED = ("ERR_OFFICIAL_SUSPENDED", 409)

# --- business safety / constraints ---
ERR_RANK_INELIGIBLE = ("ERR_RANK_INELIGIBLE", 422)
ERR_CONFLICT_OF_INTEREST = ("ERR_CONFLICT_OF_INTEREST", 422)
ERR_OUTSIDE_AVAILABILITY = ("ERR_OUTSIDE_AVAILABILITY", 422)
ERR_OFFICIAL_DOUBLE_BOOKED = ("ERR_OFFICIAL_DOUBLE_BOOKED", 409)
ERR_OUTSIDE_TRAVEL_RADIUS = ("ERR_OUTSIDE_TRAVEL_RADIUS", 422)
ERR_NOT_POSTSEASON_ELIGIBLE = ("ERR_NOT_POSTSEASON_ELIGIBLE", 422)
ERR_ASSIGNMENT_NOT_COMPLETED = ("ERR_ASSIGNMENT_NOT_COMPLETED", 409)
ERR_NOT_APPEALABLE = ("ERR_NOT_APPEALABLE", 409)

# --- ownership ---
ERR_NOT_ASSIGNMENT_OWNER = ("ERR_NOT_ASSIGNMENT_OWNER", 403)

# --- optimistic concurrency ---
ERR_STALE_GAME_VERSION = ("ERR_STALE_GAME_VERSION", 412)
ERR_STALE_OFFICIAL_VERSION = ("ERR_STALE_OFFICIAL_VERSION", 412)


def err(spec, message=None):
    """Raise an ApiError from a (error_id, http_status) tuple."""
    raise ApiError(spec[0], spec[1], message)
