"""Error catalog and the ApiError exception (PRD sections 2.2, 2.8 and 5)."""

# HTTP status per error id, taken verbatim from PRD section 5 / SCAFFOLD 1.6.
ERROR_STATUS = {
    # auth
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    # payload
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_COMMODITY_CLASS_NOT_FOUND": 404,
    "ERR_VESSEL_NOT_FOUND": 404,
    "ERR_PORT_NOT_FOUND": 404,
    "ERR_SURVEYOR_NOT_FOUND": 404,
    "ERR_CERTIFICATE_NOT_FOUND": 404,
    "ERR_ACCUMULATION_ENTRY_NOT_FOUND": 404,
    "ERR_DECLARATION_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_SURVEY_ORDER_NOT_FOUND": 404,
    "ERR_GA_EVENT_NOT_FOUND": 404,
    "ERR_GA_POSTING_NOT_FOUND": 404,
    # uniqueness
    "ERR_DUPLICATE_REFERENCE": 409,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_POLICY_NOT_ACTIVE": 409,
    "ERR_WAR_COVER_TERMINATED": 409,
    "ERR_VESSEL_BLOCKED": 422,
    "ERR_SURVEYOR_INACTIVE": 409,
    "ERR_GA_ADJUSTMENT_PENDING": 409,
    # concurrency
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_STALE_GA_EVENT_VERSION": 412,
    # safety / warranty
    "ERR_PACKAGING_WARRANTY_BREACH": 422,
    "ERR_SURVEY_REQUIRED": 422,
    # temporal
    "ERR_VOYAGE_DATES_INVALID": 422,
    "ERR_OUTSIDE_POLICY_PERIOD": 422,
    "ERR_DECLARATION_PERIOD_OVERLAP": 409,
    "ERR_SUBROGATION_TIME_BARRED": 409,
    # constraint
    "ERR_VALUATION_INPUT_MISSING": 422,
    "ERR_COMMODITY_SHARE_EXCEEDED": 422,
    "ERR_SURVEYOR_WINDOW_CONFLICT": 409,
    "ERR_SURVEYOR_NOT_CERTIFIED": 422,
    "ERR_NO_CONTRIBUTING_CERTIFICATES": 422,
    # fiscal
    "ERR_CERTIFICATE_LIMIT_EXCEEDED": 422,
    "ERR_CONVEYANCE_LIMIT_EXCEEDED": 422,
    "ERR_VESSEL_ACCUMULATION_EXCEEDED": 422,
    "ERR_PORT_ACCUMULATION_EXCEEDED": 422,
    "ERR_ANNUAL_AGGREGATE_EXCEEDED": 422,
    "ERR_SECURITY_AMOUNT_INSUFFICIENT": 422,
    "ERR_RECOVERY_EXCEEDS_SETTLEMENT": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


# Terminal states per (entity, state field) -- PRD section 2.8.
TERMINAL_STATES = {
    ("OpenPolicy", "status"): {"EXPIRED", "CANCELLED"},
    ("Certificate", "status"): {"SUPERSEDED", "CANCELLED", "TRANSIT_ENDED"},
    ("Certificate", "war_cover_status"): {"NOT_TAKEN"},
    ("ClaimFile", "status"): {"SETTLED", "DENIED"},
    ("ClaimFile", "subrogation_status"): {"RECOVERED", "TIME_BARRED"},
    ("PremiumDeclaration", "status"): {"ACCEPTED"},
    ("SurveyOrder", "status"): {"REPORT_FILED", "CANCELLED"},
    ("GeneralAverageEvent", "status"): {"ADJUSTED"},
    ("GaSecurityPosting", "status"): {"RELEASED"},
    ("AccumulationEntry", "status"): {"RELEASED"},
}


def require_state(entity, field, current, allowed_from):
    """PRD 2.8: terminal state -> ERR_ALREADY_TERMINAL, otherwise ERR_INVALID_STATE."""
    if current in allowed_from:
        return
    if current in TERMINAL_STATES.get((entity, field), frozenset()):
        raise ApiError("ERR_ALREADY_TERMINAL")
    raise ApiError("ERR_INVALID_STATE")
