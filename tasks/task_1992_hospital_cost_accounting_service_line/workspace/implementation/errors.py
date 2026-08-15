"""Error catalog (PRD §5) — ApiError carries error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)


# --- Convenience raisers, one per catalog entry ---

def missing_user_context():
    raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                   "X-User-ID and X-User-Role headers must be present and non-empty")


def insufficient_permissions(role):
    raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                   "Role '%s' is not permitted on this endpoint" % role)


def not_found(what="Resource"):
    raise ApiError("ERR_NOT_FOUND", 404, "%s does not exist" % what)


def invalid_request(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_period_format(value):
    raise ApiError("ERR_INVALID_PERIOD_FORMAT", 409,
                   "period '%s' is not in YYYY-MM format" % value)


def invalid_state(msg):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def service_line_not_active():
    raise ApiError("ERR_SERVICE_LINE_NOT_ACTIVE", 409,
                   "Referenced service line is not ACTIVE")


def model_not_active():
    raise ApiError("ERR_MODEL_NOT_ACTIVE", 409, "Referenced cost model is not ACTIVE")


def overhead_center_invalid():
    raise ApiError("ERR_OVERHEAD_CENTER_INVALID", 422,
                   "overhead_cost_center is not an ACTIVE center with cost_type OVERHEAD")


def activity_center_invalid():
    raise ApiError("ERR_ACTIVITY_CENTER_INVALID", 422,
                   "Activity line center is DIRECT, archived, or capacity_measure "
                   "mismatches the model allocation basis")


def supersede_target_invalid():
    raise ApiError("ERR_SUPERSEDE_TARGET_INVALID", 422,
                   "supersedes_model_id is not an ACTIVE model of the same service line")


def physician_not_active():
    raise ApiError("ERR_PHYSICIAN_NOT_ACTIVE", 422,
                   "Case references an INACTIVE physician")


def case_period_before_model():
    raise ApiError("ERR_CASE_PERIOD_BEFORE_MODEL", 409,
                   "Case period precedes the cost model effective_period")


def case_no_activity():
    raise ApiError("ERR_CASE_NO_ACTIVITY", 409,
                   "Post attempted with zero activity lines")


def case_stale_model():
    raise ApiError("ERR_CASE_STALE_MODEL", 409,
                   "Case version_at_post does not equal the current CostModel version")


def period_has_stale_cases():
    raise ApiError("ERR_PERIOD_HAS_STALE_CASES", 409,
                   "Budget period has POSTED cases priced under a stale model version")


def service_line_has_open_cases():
    raise ApiError("ERR_SERVICE_LINE_HAS_OPEN_CASES", 409,
                   "Archive blocked by DRAFT/POSTED cases on the line")


def service_line_has_active_model():
    raise ApiError("ERR_SERVICE_LINE_HAS_ACTIVE_MODEL", 409,
                   "Archive blocked by an ACTIVE model on the line")


def model_has_open_cases():
    raise ApiError("ERR_MODEL_HAS_OPEN_CASES", 409,
                   "Model archive blocked by DRAFT/POSTED cases")


def model_has_open_refresh():
    raise ApiError("ERR_MODEL_HAS_OPEN_REFRESH", 409,
                   "Model archive blocked by a PROPOSED/APPROVED refresh")


def cost_center_in_use():
    raise ApiError("ERR_COST_CENTER_IN_USE", 409,
                   "Cost center is referenced by a model or open-case activity lines")


def physician_has_open_cases():
    raise ApiError("ERR_PHYSICIAN_HAS_OPEN_CASES", 409,
                   "Physician deactivate blocked by DRAFT/POSTED cases")


def refresh_variance_exceeded():
    raise ApiError("ERR_REFRESH_VARIANCE_EXCEEDED", 422,
                   "A variance_report entry has abs(delta_pct) above 3.00")


def data_quality_too_low():
    raise ApiError("ERR_DATA_QUALITY_TOO_LOW", 422,
                   "data_quality_score is below 80.00")


def duplicate_budget_period():
    raise ApiError("ERR_DUPLICATE_BUDGET_PERIOD", 409,
                   "A budget period already exists for this (cost_center_id, period)")


def stale_model_version():
    raise ApiError("ERR_STALE_MODEL_VERSION", 412,
                   "expected_model_version does not match the current CostModel version")
