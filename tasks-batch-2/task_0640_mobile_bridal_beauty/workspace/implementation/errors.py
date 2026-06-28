"""Error classes and error ID constants (PRD §5 Error Code Catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status (SCAFFOLD §1.6, PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"              # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_NOT_EVENT_OWNER = "ERR_NOT_EVENT_OWNER"            # 403
ERR_STALE_EVENT_VERSION = "ERR_STALE_EVENT_VERSION"   # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_TRIAL_NOT_COMPLETED = "ERR_TRIAL_NOT_COMPLETED"   # 409
ERR_ARTIST_NOT_ACTIVE = "ERR_ARTIST_NOT_ACTIVE"       # 409
ERR_INVALID_ASSISTANT = "ERR_INVALID_ASSISTANT"       # 409
ERR_TRIAL_WINDOW_CONFLICT = "ERR_TRIAL_WINDOW_CONFLICT"          # 409
ERR_ASSIGNMENT_WINDOW_CONFLICT = "ERR_ASSIGNMENT_WINDOW_CONFLICT"  # 409
ERR_WINDOW_PAST_DEADLINE = "ERR_WINDOW_PAST_DEADLINE"  # 422
ERR_INSUFFICIENT_THROUGHPUT = "ERR_INSUFFICIENT_THROUGHPUT"  # 422
ERR_DEPOSIT_AMOUNT_MISMATCH = "ERR_DEPOSIT_AMOUNT_MISMATCH"  # 422
ERR_BALANCE_OVERPAY = "ERR_BALANCE_OVERPAY"           # 422
ERR_DEPOSIT_NOT_SETTLED = "ERR_DEPOSIT_NOT_SETTLED"   # 409
ERR_EXTENSION_PAST_DEADLINE = "ERR_EXTENSION_PAST_DEADLINE"  # 422
ERR_NO_LEAD_ARTIST = "ERR_NO_LEAD_ARTIST"             # 409
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 400


def unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def not_event_owner(msg="Acting client does not own this event"):
    return ApiError(ERR_NOT_EVENT_OWNER, 403, msg)


def stale_event_version(msg="expected_event_version does not match event version"):
    return ApiError(ERR_STALE_EVENT_VERSION, 412, msg)


def invalid_state(msg="Transition not defined from the current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def trial_not_completed(msg="Required trial session is not completed"):
    return ApiError(ERR_TRIAL_NOT_COMPLETED, 409, msg)


def artist_not_active(msg="Artist is not ACTIVE"):
    return ApiError(ERR_ARTIST_NOT_ACTIVE, 409, msg)


def invalid_assistant(msg="Assistant artist is invalid"):
    return ApiError(ERR_INVALID_ASSISTANT, 409, msg)


def trial_window_conflict(msg="Trial window overlaps another trial for this artist"):
    return ApiError(ERR_TRIAL_WINDOW_CONFLICT, 409, msg)


def assignment_window_conflict(msg="Assignment window conflicts with another window for this artist"):
    return ApiError(ERR_ASSIGNMENT_WINDOW_CONFLICT, 409, msg)


def window_past_deadline(msg="Assignment window ends past the event ready_by deadline"):
    return ApiError(ERR_WINDOW_PAST_DEADLINE, 422, msg)


def insufficient_throughput(msg="Combined throughput cannot service confirmed faces in the window"):
    return ApiError(ERR_INSUFFICIENT_THROUGHPUT, 422, msg)


def deposit_amount_mismatch(msg="Deposit payment does not exactly settle the remaining deposit"):
    return ApiError(ERR_DEPOSIT_AMOUNT_MISMATCH, 422, msg)


def balance_overpay(msg="Balance payment exceeds the current balance"):
    return ApiError(ERR_BALANCE_OVERPAY, 422, msg)


def deposit_not_settled(msg="Balance payment attempted while deposit not settled"):
    return ApiError(ERR_DEPOSIT_NOT_SETTLED, 409, msg)


def extension_past_deadline(msg="Extended-stay add-on would push past the ready_by deadline"):
    return ApiError(ERR_EXTENSION_PAST_DEADLINE, 422, msg)


def no_lead_artist(msg="No ACTIVE LEAD artist on the roster"):
    return ApiError(ERR_NO_LEAD_ARTIST, 409, msg)


def invalid_request(msg="Missing or invalid request field"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)
