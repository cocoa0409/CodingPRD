"""Custom error class and HTTP status mapping for every error_id."""


class AppError(Exception):
    """Domain error with an error_id, message, and HTTP status."""

    def __init__(self, error_id: str, message: str = "", http_status: int = 400):
        super().__init__(message)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status


# Authoritative status map (mirrors §5 Error Code Catalogue and SCAFFOLD §1.6).
ERROR_STATUS = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_ROLE_FORBIDDEN": 403,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_REVIEW_CASE_NOT_FOUND": 404,
    "ERR_CALIBRATION_SESSION_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_CYCLE_NOT_OPEN": 409,
    "ERR_PINNED_REVIEW_STALE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_PIP_ALREADY_EXISTS": 409,
    "ERR_GOAL_WEIGHTS_INVALID": 422,
    "ERR_PEER_FEEDBACK_INSUFFICIENT": 422,
    "ERR_REVISION_LIMIT": 422,
    "ERR_SELF_FEEDBACK_FORBIDDEN": 422,
    "ERR_FACILITATOR_CONFLICT": 422,
    "ERR_APPROVER_IS_MANAGER": 422,
    "ERR_PROMO_BLOCKED_BY_PIP": 422,
    "ERR_PROMO_STEP_INVALID": 422,
    "ERR_BELL_CURVE_VIOLATED": 422,
    "ERR_BELL_CURVE_TARGET_INVALID": 422,
    "ERR_CALIBRATION_COVERAGE": 422,
    "ERR_PIP_NOT_ELAPSED": 422,
    "ERR_EMAIL_TAKEN": 422,
    "ERR_MERIT_BUDGET_EXCEEDED": 422,
    "ERR_EQUITY_POOL_EXHAUSTED": 422,
    "ERR_TIME_WINDOW_INVALID": 422,
    "ERR_VALIDATION": 400,
}


def raise_err(error_id: str, message: str = "") -> None:
    """Raise an AppError with the canonical HTTP status for the given error_id."""
    status = ERROR_STATUS.get(error_id, 400)
    raise AppError(error_id, message or error_id, status)
