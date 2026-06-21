"""Error catalogue and the ApiError exception type.

Every error_id below traces to PRD §5 (Error Code Catalogue) and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries an error_id, a human-readable message, and an HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (PRD §5 / SCAFFOLD §1.6) -------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_AWARD_NOT_ACTIVE = "ERR_AWARD_NOT_ACTIVE"        # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 409
ERR_AUDIT_UNRESOLVED = "ERR_AUDIT_UNRESOLVED"        # 409
ERR_CLOSEOUT_PRECONDITIONS = "ERR_CLOSEOUT_PRECONDITIONS"  # 409
ERR_ALLOCATION_MISMATCH = "ERR_ALLOCATION_MISMATCH"  # 422
ERR_INVALID_PERIOD = "ERR_INVALID_PERIOD"            # 422
ERR_CEILING_EXCEEDED = "ERR_CEILING_EXCEEDED"        # 409
ERR_BUDGET_WOULD_EXCEED = "ERR_BUDGET_WOULD_EXCEED"  # 409
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_DUPLICATE = "ERR_DUPLICATE"                      # 409


def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Transition not defined from the resource's current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="expected_award_version does not match current Award.version."):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def award_not_active(msg="Operation requires the parent Award to be ACTIVE."):
    return ApiError(ERR_AWARD_NOT_ACTIVE, 409, msg)


def segregation_of_duties(msg="Certifier may not be a drawdown initiator on this award."):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 409, msg)


def audit_unresolved(msg="A required audit is unresolved or a MATERIAL_WEAKNESS finding is OPEN."):
    return ApiError(ERR_AUDIT_UNRESOLVED, 409, msg)


def closeout_preconditions(msg="A financial report is DRAFT/SUBMITTED or a subaward is ACTIVE."):
    return ApiError(ERR_CLOSEOUT_PRECONDITIONS, 409, msg)


def allocation_mismatch(msg="allocation_plan does not match the server-derived waterfall."):
    return ApiError(ERR_ALLOCATION_MISMATCH, 422, msg)


def invalid_period(msg="period_end_date must be strictly after period_start_date."):
    return ApiError(ERR_INVALID_PERIOD, 422, msg)


def ceiling_exceeded(msg="Drawdown would push federal_drawn_cents over federal_ceiling_cents."):
    return ApiError(ERR_CEILING_EXCEEDED, 409, msg)


def budget_would_exceed(msg="A waterfall line would push a fund's allocated_cents over its budget."):
    return ApiError(ERR_BUDGET_WOULD_EXCEED, 409, msg)


def invalid_request(msg="Invalid request body."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def duplicate(msg="Uniqueness constraint violated."):
    return ApiError(ERR_DUPLICATE, 409, msg)
