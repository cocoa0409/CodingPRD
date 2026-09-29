"""Error catalogue: every declared error id with its HTTP status."""

ERROR_STATUS = {
    # --- auth ---------------------------------------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 422,
    # --- not found ----------------------------------------------------------
    "ERR_MARKET_NOT_FOUND": 404,
    "ERR_QUOTA_CELL_NOT_FOUND": 404,
    "ERR_UNIVERSE_ESTIMATE_NOT_FOUND": 404,
    "ERR_EDIT_RULE_SET_NOT_FOUND": 404,
    "ERR_HOUSEHOLD_NOT_FOUND": 404,
    "ERR_METER_NOT_FOUND": 404,
    "ERR_TUNING_INTERVAL_NOT_FOUND": 404,
    "ERR_PROCESSING_RUN_NOT_FOUND": 404,
    "ERR_HOUSEHOLD_WEIGHT_NOT_FOUND": 404,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_CLIENT_DELIVERABLE_NOT_FOUND": 404,
    "ERR_CLIENT_NOTIFICATION_NOT_FOUND": 404,
    "ERR_METHODOLOGY_CHANGE_NOT_FOUND": 404,
    "ERR_ACCREDITATION_AUDIT_NOT_FOUND": 404,
    # --- concurrency / clock ------------------------------------------------
    "ERR_STALE_MARKET_VERSION": 412,
    "ERR_STALE_METHODOLOGY_CHANGE_VERSION": 412,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # --- recruitment / quota ------------------------------------------------
    "ERR_RECRUITMENT_CLOSED": 409,
    "ERR_MARKET_FROZEN": 409,
    "ERR_QUOTA_CELL_MARKET_MISMATCH": 422,
    "ERR_QUOTA_CELL_FILLED": 409,
    "ERR_INCENTIVE_BUDGET_EXCEEDED": 409,
    "ERR_QUOTA_CELL_DUPLICATE": 409,
    # --- household lifecycle ------------------------------------------------
    "ERR_HOUSEHOLD_NOT_ACCEPTING_METERS": 409,
    "ERR_HOUSEHOLD_NOT_ENUMERABLE": 409,
    "ERR_NO_INSTALLED_METER": 409,
    "ERR_METER_FAULTED": 409,
    "ERR_HOUSEHOLD_NOT_ACTIVE": 409,
    "ERR_HOUSEHOLD_ALREADY_RETIRED": 409,
    "ERR_INCENTIVE_PERIOD_ALREADY_ACCRUED": 409,
    "ERR_INCENTIVE_PERIOD_NOT_ACCRUED": 409,
    # --- meters -------------------------------------------------------------
    "ERR_METER_SERIAL_DUPLICATE": 409,
    "ERR_METER_TYPE_ALREADY_PRESENT": 409,
    "ERR_METER_NOT_SHIPPED": 409,
    "ERR_METER_NOT_INSTALLED": 409,
    "ERR_METER_ALREADY_FAULTED": 409,
    "ERR_METER_NOT_FAULTED": 409,
    "ERR_HOUSEHOLD_IN_TAB": 409,
    # --- universe estimates / rule sets ------------------------------------
    "ERR_UNIVERSE_CELL_COVERAGE": 422,
    "ERR_UNIVERSE_VINTAGE_DUPLICATE": 409,
    "ERR_UNIVERSE_NOT_DRAFT": 409,
    "ERR_UNIVERSE_VINTAGE_TOO_SOON": 409,
    "ERR_UNIVERSE_NOT_PUBLISHED": 409,
    "ERR_UNIVERSE_MARKET_MISMATCH": 422,
    "ERR_RULE_SET_NOT_DRAFT": 409,
    "ERR_RULE_SET_NOT_PUBLISHED": 409,
    "ERR_RULE_SET_NOT_DISTINCT": 422,
    # --- intervals ----------------------------------------------------------
    "ERR_INVALID_WINDOW": 422,
    "ERR_METHODOLOGY_METER_MISMATCH": 422,
    "ERR_INTERVAL_OVERLAP": 409,
    "ERR_INTERVAL_IN_FUTURE": 422,
    # --- processing runs ----------------------------------------------------
    "ERR_RUN_WINDOW_OUTSIDE_UNIVERSE": 422,
    "ERR_RUN_WINDOW_OVERLAP": 409,
    "ERR_RUN_NOT_OPEN": 409,
    "ERR_RUN_NOT_EDITED": 409,
    "ERR_RUN_NOT_WEIGHTED": 409,
    "ERR_RUN_NOT_PENDING_REPIN": 409,
    "ERR_RUN_NOT_PUBLISHED": 409,
    "ERR_RUN_SUPERSEDED": 409,
    "ERR_NO_CONTRIBUTING_HOUSEHOLDS": 409,
    "ERR_DESIGN_DENOMINATOR_EMPTY": 409,
    "ERR_PUBLICATION_BLOCKED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    # --- clients / deliverables --------------------------------------------
    "ERR_CLIENT_SUSPENDED": 409,
    "ERR_CLIENT_NOT_SUSPENDED": 409,
    "ERR_MARKET_NOT_CONTRACTED": 403,
    "ERR_CUSTOM_ANALYSIS_QUOTA_EXCEEDED": 409,
    "ERR_DELIVERABLE_NOT_DELIVERABLE": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_DELIVERABLE_NOT_HELD": 409,
    # --- methodology governance --------------------------------------------
    "ERR_CHANGE_NOT_DRAFT": 409,
    "ERR_BASELINE_RUN_INVALID": 422,
    "ERR_CHANGE_NOT_ASSESSED": 409,
    "ERR_CHANGE_NOT_NOTIFIED": 409,
    "ERR_ACKNOWLEDGEMENTS_MISSING": 409,
    "ERR_NOTIFICATION_PERIOD_OPEN": 409,
    "ERR_NOTIFICATION_NOT_SENT": 409,
    "ERR_NO_AFFECTED_CLIENTS": 409,
    # --- accreditation ------------------------------------------------------
    "ERR_AUDIT_ALREADY_OPEN": 409,
    "ERR_AUDIT_NOT_OPEN": 409,
    "ERR_DISCLOSURE_REQUIRED": 422,
}


class ApiError(Exception):
    """Raised anywhere in a handler; rendered by the global error handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 422)
