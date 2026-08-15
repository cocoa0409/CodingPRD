"""Error classes and error ID constants (from SCAFFOLD error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Auth / generic
ERR_MISSING_CONTEXT = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"   # 400
ERR_FORBIDDEN = "ERR_INSUFFICIENT_PERMISSIONS"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                       # 404
ERR_STALE_VERSION = "ERR_STALE_VERSION"                               # 412
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                           # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                               # 409

# InjuryCase
ERR_CASE_NOT_OPEN = "ERR_CASE_NOT_OPEN"                               # 409
ERR_NO_STATUS_ENTRY = "ERR_NO_STATUS_ENTRY"                           # 409
ERR_CASE_NOT_IN_REHAB = "ERR_CASE_NOT_IN_REHAB"                       # 409
ERR_RTP_ALREADY_EXISTS = "ERR_RTP_ALREADY_EXISTS"                     # 409
ERR_NO_ACTIVE_TREATMENT_PLAN = "ERR_NO_ACTIVE_TREATMENT_PLAN"         # 409
ERR_CASE_NOT_CLEARED = "ERR_CASE_NOT_CLEARED"                         # 409
ERR_PLAN_STILL_ACTIVE = "ERR_PLAN_STILL_ACTIVE"                       # 409
ERR_CLAIMS_OPEN = "ERR_CLAIMS_OPEN"                                   # 409
ERR_DESIGNATION_NOT_OUT = "ERR_DESIGNATION_NOT_OUT"                   # 409
ERR_CASE_NOT_LONG_TERM = "ERR_CASE_NOT_LONG_TERM"                     # 409

# TreatmentPlan
ERR_PLAN_NOT_DRAFT = "ERR_PLAN_NOT_DRAFT"                             # 409
ERR_PLAN_NOT_ACTIVE = "ERR_PLAN_NOT_ACTIVE"                           # 409
ERR_PLAN_NOT_SUSPENDED = "ERR_PLAN_NOT_SUSPENDED"                     # 409
ERR_PLAN_NOT_COMPLETABLE = "ERR_PLAN_NOT_COMPLETABLE"                 # 409

# RTP
ERR_PROTOCOL_NOT_ADVANCEABLE = "ERR_PROTOCOL_NOT_ADVANCEABLE"         # 409
ERR_READINESS_NOT_MET = "ERR_READINESS_NOT_MET"                       # 409
ERR_CONCUSSION_MIN_DAYS = "ERR_CONCUSSION_MIN_DAYS"                   # 409
ERR_PROTOCOL_NOT_REGRESSABLE = "ERR_PROTOCOL_NOT_REGRESSABLE"         # 409
ERR_CANNOT_REGRESS_BELOW_ZERO = "ERR_CANNOT_REGRESS_BELOW_ZERO"       # 409
ERR_PROTOCOL_NOT_AWAITING_CLEARANCE = "ERR_PROTOCOL_NOT_AWAITING_CLEARANCE"  # 409

# Clearance
ERR_CLEARANCE_NOT_PENDING = "ERR_CLEARANCE_NOT_PENDING"               # 409
ERR_CLEARANCE_ALREADY_PENDING = "ERR_CLEARANCE_ALREADY_PENDING"       # 409
ERR_SOD_SELF_CLEARANCE = "ERR_SOD_SELF_CLEARANCE"                     # 403
ERR_SOD_EVALUATOR_CLEARANCE = "ERR_SOD_EVALUATOR_CLEARANCE"           # 403
ERR_STALE_EVALUATION = "ERR_STALE_EVALUATION"                         # 409
ERR_NO_FRESH_STATUS_ENTRY = "ERR_NO_FRESH_STATUS_ENTRY"               # 409

# Claims / policies
ERR_CLAIM_NOT_DRAFT = "ERR_CLAIM_NOT_DRAFT"                           # 409
ERR_CLAIM_NOT_SUBMITTABLE_STATE = "ERR_CLAIM_NOT_SUBMITTABLE_STATE"   # 409
ERR_CLAIM_NOT_DENIED = "ERR_CLAIM_NOT_DENIED"                         # 409
ERR_CLAIM_NOT_VOIDABLE = "ERR_CLAIM_NOT_VOIDABLE"                     # 409
ERR_MAX_APPEALS_REACHED = "ERR_MAX_APPEALS_REACHED"                   # 409
ERR_POLICY_NOT_ACTIVE = "ERR_POLICY_NOT_ACTIVE"                       # 409
ERR_POLICY_CLAIMS_IN_FLIGHT = "ERR_POLICY_CLAIMS_IN_FLIGHT"           # 409
ERR_SERVICE_DATE_OUT_OF_POLICY_YEAR = "ERR_SERVICE_DATE_OUT_OF_POLICY_YEAR"  # 422
ERR_LINE_ITEM_SUM_MISMATCH = "ERR_LINE_ITEM_SUM_MISMATCH"             # 422
ERR_INVALID_SUPERSEDE_TARGET = "ERR_INVALID_SUPERSEDE_TARGET"         # 422
ERR_FUTURE_DATE_NOT_ALLOWED = "ERR_FUTURE_DATE_NOT_ALLOWED"           # 422
ERR_DUPLICATE_POLICY_NUMBER = "ERR_DUPLICATE_POLICY_NUMBER"           # 409

# Athlete
ERR_ATHLETE_NOT_ACTIVE = "ERR_ATHLETE_NOT_ACTIVE"                     # 409
ERR_ATHLETE_NOT_INACTIVE = "ERR_ATHLETE_NOT_INACTIVE"                 # 409
ERR_OPEN_CASES_EXIST = "ERR_OPEN_CASES_EXIST"                         # 409

# Grants / reports
ERR_GRANT_NOT_ACTIVE = "ERR_GRANT_NOT_ACTIVE"                         # 409
ERR_AUDIENCE_INVALID = "ERR_AUDIENCE_INVALID"                         # 400


def bad_request(msg):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def conflict(error_id, msg):
    return ApiError(error_id, 409, msg)


def unprocessable(error_id, msg):
    return ApiError(error_id, 422, msg)
