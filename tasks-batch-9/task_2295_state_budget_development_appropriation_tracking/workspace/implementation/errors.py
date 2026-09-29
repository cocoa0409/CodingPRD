"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""

ERROR_STATUS = {
    # --- auth -------------------------------------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_AGENCY_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence --------------------------------------------------------
    "ERR_AGENCY_NOT_FOUND": 404,
    "ERR_BUDGET_CYCLE_NOT_FOUND": 404,
    "ERR_REVENUE_FORECAST_NOT_FOUND": 404,
    "ERR_AGENCY_REQUEST_NOT_FOUND": 404,
    "ERR_DECISION_PACKAGE_NOT_FOUND": 404,
    "ERR_RECOMMENDATION_NOT_FOUND": 404,
    "ERR_APPROPRIATION_NOT_FOUND": 404,
    "ERR_ALLOTMENT_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_EXPENDITURE_NOT_FOUND": 404,
    "ERR_FEDERAL_GRANT_NOT_FOUND": 404,
    "ERR_MATCH_COMMITMENT_NOT_FOUND": 404,
    # --- request shape ----------------------------------------------------
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_AMOUNT": 422,
    "ERR_PERFORMANCE_TARGET_INVALID": 422,
    # --- concurrency ------------------------------------------------------
    "ERR_STALE_VERSION": 412,
    # --- state ------------------------------------------------------------
    "ERR_CYCLE_PHASE_INVALID": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_APPROPRIATION_NOT_ENACTED": 409,
    "ERR_CASH_FROZEN": 409,
    "ERR_RELEASE_HOLD_ACTIVE": 409,
    # --- referential ------------------------------------------------------
    "ERR_DEPENDENCY_DEFERRED": 422,
    "ERR_DEPENDENCY_NOT_RECOMMENDED": 422,
    "ERR_PACKAGE_NOT_RECOMMENDED": 422,
    "ERR_PACKAGE_REQUEST_MISMATCH": 422,
    "ERR_PERFORMANCE_MEASURE_REQUIRED": 422,
    # --- temporal ---------------------------------------------------------
    "ERR_QUARTER_CLOSED": 409,
    "ERR_QUARTER_NOT_OPEN": 409,
    "ERR_CYCLE_NOT_ENDED": 409,
    "ERR_FORECAST_WINDOW_CONFLICT": 409,
    # --- uniqueness -------------------------------------------------------
    "ERR_ALLOTMENT_QUARTER_OCCUPIED": 409,
    "ERR_ACTION_SEQUENCE_DUPLICATE": 409,
    "ERR_DUPLICATE_PRIORITY_RANK": 409,
    "ERR_DUPLICATE_AGENCY_REQUEST": 409,
    "ERR_DUPLICATE_CODE": 409,
    # --- transfer structure ----------------------------------------------
    "ERR_TRANSFER_SAME_APPROPRIATION": 422,
    "ERR_TRANSFER_FUND_TYPE_MISMATCH": 422,
    "ERR_TRANSFER_TYPE_MISMATCH": 422,
    # --- fiscal -----------------------------------------------------------
    "ERR_NEGATIVE_APPROPRIATION_BALANCE": 422,
    "ERR_TRANSFER_EXCEEDS_AUTHORITY_CAP": 422,
    "ERR_TRANSFER_EXCEEDS_AVAILABLE": 422,
    "ERR_APPROPRIATION_OVERSPEND": 422,
    "ERR_INSUFFICIENT_CASH_RELEASED": 422,
    "ERR_NO_RELEASE_CAPACITY": 422,
    "ERR_ALLOTMENT_EXCEEDS_CEILING": 422,
    "ERR_NO_ADOPTED_FORECAST": 422,
    "ERR_BUDGET_NOT_BALANCED": 422,
    "ERR_EMERGENCY_EXCEEDS_RESERVE_CAPACITY": 422,
    "ERR_MATCH_AGGREGATE_CAPACITY_EXCEEDED": 422,
    "ERR_NO_REDUCTION_CANDIDATES": 422,
    # --- fallback ---------------------------------------------------------
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    """A rejection carrying the catalogued error_id and its HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)
        super().__init__(self.message)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)
