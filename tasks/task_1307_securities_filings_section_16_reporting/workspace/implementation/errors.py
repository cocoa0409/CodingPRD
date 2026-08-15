"""Error classes and error ID constants for the Section 16 filings API."""


class ApiError(Exception):
    """Carries an error_id, message, and HTTP status code."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Error IDs (from SCAFFOLD errors table / PRD §5) ---
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_PERSON_INVALID_STATE = "ERR_PERSON_INVALID_STATE"
ERR_PERSON_NOT_ACTIVE = "ERR_PERSON_NOT_ACTIVE"
ERR_TRANSACTION_INVALID_STATE = "ERR_TRANSACTION_INVALID_STATE"
ERR_FILING_INVALID_STATE = "ERR_FILING_INVALID_STATE"
ERR_PLAN_INVALID_STATE = "ERR_PLAN_INVALID_STATE"
ERR_SWEEP_INVALID_STATE = "ERR_SWEEP_INVALID_STATE"
ERR_AUTHORIZATION_INVALID_STATE = "ERR_AUTHORIZATION_INVALID_STATE"
ERR_FUTURE_TRANSACTION_DATE = "ERR_FUTURE_TRANSACTION_DATE"
ERR_FUTURE_EFFECTIVE_DATE = "ERR_FUTURE_EFFECTIVE_DATE"
ERR_PLAN_NOT_ACTIVE = "ERR_PLAN_NOT_ACTIVE"
ERR_PLAN_PERSON_MISMATCH = "ERR_PLAN_PERSON_MISMATCH"
ERR_COOLING_OFF_NOT_SATISFIED = "ERR_COOLING_OFF_NOT_SATISFIED"
ERR_BLACKOUT_PERIOD = "ERR_BLACKOUT_PERIOD"
ERR_BLACKOUT_WINDOW_OVERLAP = "ERR_BLACKOUT_WINDOW_OVERLAP"
ERR_PLAN_WINDOW_OVERLAP = "ERR_PLAN_WINDOW_OVERLAP"
ERR_DUPLICATE_SWEEP = "ERR_DUPLICATE_SWEEP"
ERR_AMENDMENT_TARGET_NOT_ACCEPTED = "ERR_AMENDMENT_TARGET_NOT_ACCEPTED"
ERR_EDGAR_CREDENTIAL_MISMATCH = "ERR_EDGAR_CREDENTIAL_MISMATCH"
ERR_AGENT_NOT_AUTHORIZED = "ERR_AGENT_NOT_AUTHORIZED"
ERR_SOD_PREPARER_SUBMITTER = "ERR_SOD_PREPARER_SUBMITTER"
ERR_SOD_INGESTER_CONFIRMER = "ERR_SOD_INGESTER_CONFIRMER"
ERR_SCHEDULE_NOT_REQUIRED = "ERR_SCHEDULE_NOT_REQUIRED"
ERR_TRANSACTION_NOT_ATTACHABLE = "ERR_TRANSACTION_NOT_ATTACHABLE"


def missing_or_invalid_user_context():
    return ApiError(
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        "X-User-ID and X-User-Role headers must be present and non-empty.",
        400,
    )


def forbidden_role(msg="Role not permitted for the operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, msg, 403)


def not_found(resource="resource"):
    return ApiError(ERR_NOT_FOUND, f"{resource} not found.", 404)


def invalid_request(msg="Malformed request body."):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def stale_version(msg="Stale version."):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def person_invalid_state():
    return ApiError(ERR_PERSON_INVALID_STATE, "ReportingPerson transition attempted from a state that does not allow it.", 409)


def person_not_active():
    return ApiError(ERR_PERSON_NOT_ACTIVE, "Operation requires the ReportingPerson to be ACTIVE.", 409)


def transaction_invalid_state():
    return ApiError(ERR_TRANSACTION_INVALID_STATE, "Transaction transition attempted from a disallowed state.", 409)


def filing_invalid_state():
    return ApiError(ERR_FILING_INVALID_STATE, "Filing transition attempted from a disallowed state.", 409)


def plan_invalid_state():
    return ApiError(ERR_PLAN_INVALID_STATE, "Trading plan transition attempted from a disallowed state.", 409)


def sweep_invalid_state():
    return ApiError(ERR_SWEEP_INVALID_STATE, "Run attempted on a non-OPEN sweep.", 409)


def authorization_invalid_state():
    return ApiError(ERR_AUTHORIZATION_INVALID_STATE, "Revoke attempted on a non-ACTIVE authorization.", 409)


def future_transaction_date():
    return ApiError(ERR_FUTURE_TRANSACTION_DATE, "transaction_date is later than the logical clock date.", 422)


def future_effective_date():
    return ApiError(ERR_FUTURE_EFFECTIVE_DATE, "PositionChange effective_date is later than the logical clock date.", 422)


def plan_not_active():
    return ApiError(ERR_PLAN_NOT_ACTIVE, "Plan-affiliated transaction confirmed while the 10b5-1 plan is not ACTIVE.", 422)


def plan_person_mismatch():
    return ApiError(ERR_PLAN_PERSON_MISMATCH, "plan_id references a plan whose reporting_person_id differs from the transaction's.", 422)


def cooling_off_not_satisfied():
    return ApiError(ERR_COOLING_OFF_NOT_SATISFIED, "ACTIVATE attempted before the logical clock date reaches cooling_off_end_date.", 422)


def blackout_period():
    return ApiError(ERR_BLACKOUT_PERIOD, "Non-plan transaction's transaction_date falls inside an issuer blackout window.", 422)


def blackout_window_overlap():
    return ApiError(ERR_BLACKOUT_WINDOW_OVERLAP, "New blackout window shares at least one calendar date with an existing window of the same issuer.", 409)


def plan_window_overlap():
    return ApiError(ERR_PLAN_WINDOW_OVERLAP, "Approved plan's half-open window intersects another ADOPTED/ACTIVE/SUSPENDED plan of the same person.", 409)


def duplicate_sweep():
    return ApiError(ERR_DUPLICATE_SWEEP, "An OPEN or COMPLETED sweep already exists for (issuer_id, fiscal_year).", 409)


def amendment_target_not_accepted():
    return ApiError(ERR_AMENDMENT_TARGET_NOT_ACCEPTED, "Amendment attempted against a filing not in ACCEPTED status.", 409)


def edgar_credential_mismatch():
    return ApiError(ERR_EDGAR_CREDENTIAL_MISMATCH, "Submit payload edgar_ccc does not equal the issuer's current edgar_ccc.", 422)


def agent_not_authorized():
    return ApiError(ERR_AGENT_NOT_AUTHORIZED, "No ACTIVE FilingAgentAuthorization for (filing.issuer_id, X-User-ID).", 403)


def sod_preparer_submitter():
    return ApiError(ERR_SOD_PREPARER_SUBMITTER, "Submitter X-User-ID equals the filing's non-null prepared_by_user_id.", 403)


def sod_ingester_confirmer():
    return ApiError(ERR_SOD_INGESTER_CONFIRMER, "Confirmer X-User-ID equals the transaction's ingested_by_user_id.", 403)


def schedule_not_required():
    return ApiError(ERR_SCHEDULE_NOT_REQUIRED, "file-schedule attempted while holder status is not FILING_REQUIRED or AMENDMENT_REQUIRED.", 409)


def transaction_not_attachable():
    return ApiError(ERR_TRANSACTION_NOT_ATTACHABLE, "Manual FORM_4 transaction_ids contain a transaction that is not CONFIRMED, is already filed, or belongs to a different person.", 422)
