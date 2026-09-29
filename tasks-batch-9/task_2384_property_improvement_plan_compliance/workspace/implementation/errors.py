"""Error catalogue (PRD section 5) and the ApiError exception."""


# error_id -> HTTP status
ERROR_HTTP = {
    # --- auth / authz -----------------------------------------------------
    "ERR_MISSING_ROLE": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_MISSING_USER_ID": 401,
    "ERR_UNAUTHORIZED": 403,
    # --- existence --------------------------------------------------------
    "ERR_FRANCHISEE_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_EXTENSION_REQUEST_NOT_FOUND": 404,
    "ERR_BUDGET_NOT_FOUND": 404,
    "ERR_DRAW_NOT_FOUND": 404,
    "ERR_PHASE_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_PUNCH_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    # --- request shape ----------------------------------------------------
    "ERR_VALIDATION": 422,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_ROOM_IMPACT_MISMATCH": 422,
    "ERR_CONTINGENCY_OUT_OF_RANGE": 422,
    "ERR_CURE_PERIOD_OUT_OF_RANGE": 422,
    "ERR_JUSTIFICATION_INSUFFICIENT": 422,
    "ERR_PHASE_NUMBER_DUPLICATE": 409,
    "ERR_REVISION_COST_REQUIRED": 422,
    "ERR_REVISION_NOT_ALLOWED_FOR_RESOLUTION": 422,
    # --- state preconditions ---------------------------------------------
    "ERR_PLAN_NOT_ISSUABLE": 409,
    "ERR_PLAN_NOT_ACKNOWLEDGEABLE": 409,
    "ERR_PLAN_NOT_WITHDRAWABLE": 409,
    "ERR_PLAN_NOT_DRAFT": 409,
    "ERR_PLAN_NOT_IN_EXECUTION_WINDOW": 409,
    "ERR_PLAN_NOT_READY_FOR_SIGNOFF": 409,
    "ERR_PLAN_HAS_NO_ITEMS": 409,
    "ERR_ITEM_NOT_STARTABLE": 409,
    "ERR_ITEM_NOT_IN_PROGRESS": 409,
    "ERR_ITEM_NOT_REMOVABLE": 409,
    "ERR_EXTENSION_NOT_DECIDABLE": 409,
    "ERR_EXTENSION_NOT_RESUBMITTABLE": 409,
    "ERR_BUDGET_NOT_APPROVABLE": 409,
    "ERR_BUDGET_NOT_LOCKABLE": 409,
    "ERR_DRAW_NOT_DECIDABLE": 409,
    "ERR_DRAW_NOT_DISBURSABLE": 409,
    "ERR_DRAW_NOT_REVERSIBLE": 409,
    "ERR_PHASE_NOT_ACTIVATABLE": 409,
    "ERR_PHASE_NOT_CLOSEABLE": 409,
    "ERR_INSPECTION_NOT_PERFORMABLE": 409,
    "ERR_INSPECTION_NOT_SIGNABLE": 409,
    "ERR_INSPECTION_TYPE_NOT_SIGNABLE": 409,
    "ERR_PUNCH_NOT_REMEDIABLE": 409,
    "ERR_PUNCH_NOT_VERIFIABLE": 409,
    "ERR_DISPUTE_NOT_RESOLVABLE": 409,
    "ERR_DISPUTE_ALREADY_OPEN": 409,
    "ERR_NOTICE_NOT_ACTIONABLE": 409,
    "ERR_FRANCHISE_TERMINATED": 409,
    "ERR_BREACH_NOT_CURED": 409,
    "ERR_BREACH_ALREADY_CURED": 409,
    # --- optimistic concurrency ------------------------------------------
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_STALE_PROPERTY_VERSION": 412,
    # --- safety -----------------------------------------------------------
    "ERR_LIFE_SAFETY_PRIORITY_VIOLATION": 409,
    "ERR_NO_ACTIVE_PHASE_FOR_ROOM_WORK": 409,
    "ERR_OOO_CAP_EXCEEDED": 409,
    "ERR_CRITICAL_DEFECT_NOT_WAIVABLE": 409,
    "ERR_PUNCH_LIST_OPEN": 409,
    "ERR_CURE_PERIOD_TOO_LONG_FOR_LIFE_SAFETY": 422,
    "ERR_CONTRACTOR_NOT_BRAND_APPROVED": 409,
    "ERR_ROOM_WORK_STILL_IN_PROGRESS": 409,
    # --- temporal ---------------------------------------------------------
    "ERR_INSPECTION_TOO_EARLY": 409,
    "ERR_CURE_PERIOD_NOT_ELAPSED": 409,
    "ERR_PHASE_WINDOW_CONFLICT": 409,
    "ERR_CONTRACTOR_DOUBLE_BOOKED": 409,
    "ERR_BOOKING_OUTSIDE_PHASE_WINDOW": 422,
    "ERR_PHASE_OUTSIDE_PLAN_HORIZON": 422,
    "ERR_NO_BREACH_TO_NOTICE": 409,
    "ERR_EXTENSION_AFTER_DEADLINE": 409,
    # --- referential / duty separation -----------------------------------
    "ERR_PREDECESSOR_PLAN_MISMATCH": 422,
    "ERR_PREDECESSOR_NOT_SATISFIED": 409,
    "ERR_PREDECESSOR_CYCLE": 422,
    "ERR_ITEM_PLAN_MISMATCH": 422,
    "ERR_DRAW_ITEM_PLAN_MISMATCH": 422,
    "ERR_DRAW_PROPERTY_MISMATCH": 422,
    "ERR_NOT_PROPERTY_FRANCHISEE": 403,
    "ERR_NOT_ASSIGNED_INSPECTOR": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DISPUTE_OPEN_BLOCKS_SIGNOFF": 409,
    # --- aggregate / quota ------------------------------------------------
    "ERR_EXTENSION_ALREADY_PENDING": 409,
    "ERR_EXTENSION_ROUNDS_EXHAUSTED": 409,
    "ERR_EXTENSION_CAP_EXHAUSTED": 409,
    # --- fiscal -----------------------------------------------------------
    "ERR_BUDGET_UNDERFUNDED": 409,
    "ERR_BUDGET_NOT_LOCKED": 409,
    "ERR_BUDGET_NOT_FUNDABLE": 409,
    "ERR_INSUFFICIENT_RESERVE": 409,
    "ERR_DRAW_EXCEEDS_BUDGET": 409,
    "ERR_BUDGET_CLOSED": 409,
    # --- generic ----------------------------------------------------------
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


DEFAULT_MESSAGES = {
    "ERR_MISSING_ROLE": "X-User-Role header is required",
    "ERR_INVALID_ROLE": "X-User-Role header carries an unrecognised role",
    "ERR_MISSING_USER_ID": "X-User-ID header is required",
    "ERR_UNAUTHORIZED": "role is not permitted to perform this operation",
}


class ApiError(Exception):
    """Domain error carrying the catalogue error id, message and HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").lower()
        )
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        super().__init__(self.message)
