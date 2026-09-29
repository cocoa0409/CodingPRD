"""Error catalogue (PRD section 5) — 69 error ids with their HTTP statuses."""

ERROR_HTTP = {
    # --- auth ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    # --- not found ---
    "ERR_MODEL_NOT_FOUND": 404,
    "ERR_TRAINING_DATASET_NOT_FOUND": 404,
    "ERR_MODEL_VERSION_NOT_FOUND": 404,
    "ERR_SERVING_ENDPOINT_NOT_FOUND": 404,
    "ERR_DEPLOYMENT_NOT_FOUND": 404,
    "ERR_TRAFFIC_RAMP_STEP_NOT_FOUND": 404,
    "ERR_MONITORING_WINDOW_NOT_FOUND": 404,
    "ERR_DRIFT_REPORT_NOT_FOUND": 404,
    "ERR_SKEW_CHECK_NOT_FOUND": 404,
    "ERR_RETRAINING_TRIGGER_NOT_FOUND": 404,
    "ERR_CHALLENGER_EVALUATION_NOT_FOUND": 404,
    "ERR_PREDICTION_INCIDENT_NOT_FOUND": 404,
    "ERR_REVALIDATION_TASK_NOT_FOUND": 404,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_INTERVAL": 400,
    "ERR_INVALID_BIN_PROPORTIONS": 400,
    "ERR_LABEL_COUNT_INCONSISTENT": 400,
    "ERR_INVALID_FEATURE_STATS": 400,
    "ERR_INVALID_METRIC_SET": 400,
    # --- optimistic concurrency ---
    "ERR_STALE_SERVING_ENDPOINT_VERSION": 412,
    "ERR_STALE_MODEL_VERSION": 412,
    # --- state ---
    "ERR_TERMINAL_STATE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_WINDOW_NOT_ENDED": 409,
    "ERR_WINDOW_NOT_CLOSED": 409,
    "ERR_RAMP_ALREADY_COMPLETE": 409,
    "ERR_MANUAL_OVERRIDE_ACTIVE": 409,
    "ERR_CLOCK_REGRESSION": 409,
    # --- segregation of duties ---
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- safety / compliance ---
    "ERR_DOCUMENTATION_INCOMPLETE": 422,
    "ERR_PII_REVIEW_MISSING": 422,
    "ERR_HEALTH_CRITICAL_BLOCKED": 422,
    "ERR_OPEN_INCIDENT_BLOCKS_ACTION": 422,
    "ERR_SKEW_CHECK_FAILED": 422,
    "ERR_FALLBACK_NOT_CONFIGURED": 422,
    "ERR_OVERRIDE_EXCEEDS_CURRENT_TRAFFIC": 422,
    # --- referential / cross-entity ---
    "ERR_DATASET_NOT_APPROVED": 422,
    "ERR_VERSION_NOT_APPROVED": 422,
    "ERR_SERVING_ENDPOINT_NOT_OPEN": 422,
    "ERR_FEATURE_SPEC_MISMATCH": 422,
    "ERR_WINDOW_VERSION_MISMATCH": 422,
    "ERR_SKEW_DEPLOYMENT_MISMATCH": 422,
    "ERR_CHALLENGER_MODEL_MISMATCH": 422,
    "ERR_LINEAGE_MODEL_MISMATCH": 422,
    "ERR_RETRAINED_VERSION_LINEAGE_INVALID": 422,
    # --- uniqueness / constraint ---
    "ERR_DUPLICATE_MODEL_NAME": 409,
    "ERR_DUPLICATE_SEMVER": 409,
    "ERR_DUPLICATE_SERVING_ENDPOINT_NAME": 409,
    "ERR_DUPLICATE_OPEN_WINDOW": 409,
    "ERR_ACTIVE_EVALUATION_EXISTS": 409,
    "ERR_CHALLENGER_NOT_SHADOW": 422,
    "ERR_MAX_EXTENSIONS_REACHED": 409,
    "ERR_RETRAIN_REQUIRED": 409,
    "ERR_VERSION_STILL_SERVING": 409,
    "ERR_CANNOT_DEPRECATE_CHAMPION": 409,
    "ERR_MODEL_ARCHIVED": 409,
    # --- temporal ---
    "ERR_SERVE_WINDOW_CONFLICT": 409,
    "ERR_MONITORING_WINDOW_OVERLAP": 409,
    "ERR_SERVE_WINDOW_EXPIRED": 409,
    "ERR_EVALUATION_NOT_MATURE": 409,
    "ERR_CHALLENGER_NOT_SERVING": 409,
    "ERR_CHAMPION_NOT_LIVE": 409,
    "ERR_DEPLOYMENT_NOT_SERVING": 409,
    # --- capacity / quota ---
    "ERR_ENDPOINT_CAPACITY_EXHAUSTED": 409,
    "ERR_SAMPLE_BUDGET_EXCEEDED": 409,
    "ERR_NO_LABELED_PREDICTIONS": 422,
}


class ApiError(Exception):
    """Carries error_id, message and http_status through to the error envelope."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        if message is None:
            message = error_id[4:].replace("_", " ").lower() if error_id.startswith(
                "ERR_") else error_id
        self.message = message


def fail(error_id, message=None):
    raise ApiError(error_id, message)
