"""Error catalog for the fluid-power shop API.

Every error_id and HTTP status is taken verbatim from PRD section 5.
"""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- factory helpers (exact error_ids + statuses from the PRD error catalog) ---

def err_invalid_request(msg="Malformed body, missing required field, invalid type or enum member"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_unauthenticated(msg="Missing/unknown X-User-Role or X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_owner(msg="Entity-backed caller does not own / is not assigned to the target resource"):
    return ApiError("ERR_NOT_OWNER", msg, 403)


def err_not_found(msg="Path id or body foreign key references a non-existent resource"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_stale_version(msg="expected version does not match the parent entity's current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_invalid_state(msg="Target resource is not in a valid from-state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_already_terminal(msg="Target resource is in a terminal state; no further transitions"):
    return ApiError("ERR_ALREADY_TERMINAL", msg, 409)


def err_quote_not_approvable(msg="Quote is not SENT"):
    return ApiError("ERR_QUOTE_NOT_APPROVABLE", msg, 409)


def err_quote_expired(msg="Approve attempted after sent_at + quote_ttl_hours; quote flips to EXPIRED"):
    return ApiError("ERR_QUOTE_EXPIRED", msg, 409)


def err_active_quote_exists(msg="Work order already has a quote in DRAFT or SENT"):
    return ApiError("ERR_ACTIVE_QUOTE_EXISTS", msg, 409)


def err_teardown_report_exists(msg="A teardown report already exists for the work order"):
    return ApiError("ERR_TEARDOWN_REPORT_EXISTS", msg, 409)


def err_teardown_stale(msg="Quote pinned to a superseded TeardownReport version; cannot be sent"):
    return ApiError("ERR_TEARDOWN_STALE", msg, 409)


def err_scrap_not_authorized(msg="complete-scrap attempted before customer authorize-scrap"):
    return ApiError("ERR_SCRAP_NOT_AUTHORIZED", msg, 409)


def err_cylinder_retired(msg="Work order creation on a RETIRED or EXCHANGED cylinder"):
    return ApiError("ERR_CYLINDER_RETIRED", msg, 409)


def err_customer_suspended(msg="Work order creation for a SUSPENDED customer"):
    return ApiError("ERR_CUSTOMER_SUSPENDED", msg, 409)


def err_cleanliness(msg="complete-assembly with cleanliness_passed false"):
    return ApiError("ERR_CLEANLINESS_CLASS_EXCEEDED", msg, 422)


def err_segregation(msg="Certification attempted by the same user id that is the work order's assigned technician"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 422)


def err_pressure_hold(msg="record-result passed=true but measured hold, duration, or leakage does not satisfy the pass rule"):
    return ApiError("ERR_PRESSURE_HOLD_INSUFFICIENT", msg, 422)


def err_crimp(msg="An assembly's measured crimp diameter deviates from spec by more than crimp_tolerance_mm"):
    return ApiError("ERR_CRIMP_OUT_OF_TOLERANCE", msg, 422)


def err_seal_kit(msg="Seal kit bore range, pressure-class ceiling, or fluid compatibility does not cover the cylinder spec"):
    return ApiError("ERR_SEAL_KIT_INCOMPATIBLE", msg, 422)


def err_bay_overlap(msg="Bay booking collides with another booking once the mandatory buffer is added to both sides"):
    return ApiError("ERR_TEST_BAY_WINDOW_OVERLAP", msg, 409)


def err_tech_overlap(msg="Technician half-open window overlap with another SCHEDULED/DISPATCHED field job"):
    return ApiError("ERR_TECHNICIAN_WINDOW_OVERLAP", msg, 409)


def err_window_past(msg="Scheduled window starts before the current logical clock"):
    return ApiError("ERR_WINDOW_IN_PAST", msg, 409)


def err_promise(msg="promised_hours demands a faster turnaround tier than requested"):
    return ApiError("ERR_PROMISE_INFEASIBLE", msg, 422)


def err_spec_mismatch(msg="Exchange unit bore/stroke/rod/pressure-class do not exactly match the cylinder"):
    return ApiError("ERR_SPEC_MISMATCH", msg, 422)


def err_no_stock(msg="No AVAILABLE inventory piece of the material/diameter with length_mm >= cut_length_mm + kerf_mm"):
    return ApiError("ERR_NO_STOCK_FITS", msg, 409)


def err_unit_not_in_pool(msg="Exchange unit not IN_POOL when selected"):
    return ApiError("ERR_UNIT_NOT_IN_POOL", msg, 409)


def err_reservation_not_open(msg="Reservation not in expected state"):
    return ApiError("ERR_RESERVATION_NOT_OPEN", msg, 409)


def err_certificate_exists(msg="An ISSUED certificate already exists for the work order"):
    return ApiError("ERR_CERTIFICATE_EXISTS", msg, 409)


def err_credit_limit(msg="Open approved-quote exposure plus this quote exceeds customer credit limit"):
    return ApiError("ERR_CREDIT_LIMIT_EXCEEDED", msg, 402)


def err_exchange_not_fulfilled(msg="receive-core attempted before fulfill"):
    return ApiError("ERR_EXCHANGE_NOT_FULFILLED", msg, 409)


def err_core_not_returned(msg="Exchange work-order close attempted before the exchange deal is SETTLED"):
    return ApiError("ERR_CORE_NOT_RETURNED", msg, 409)
