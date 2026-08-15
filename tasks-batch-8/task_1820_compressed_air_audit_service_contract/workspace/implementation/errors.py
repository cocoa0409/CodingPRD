"""Error classes and the scaffold's error-id catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- auth / generic ---
ERR_AUTH_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"      # 400
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"                   # 403
ERR_FACILITY_OWNERSHIP_MISMATCH = "ERR_FACILITY_OWNERSHIP_MISMATCH"  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                     # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                         # 400
ERR_INVALID_STATE_TRANSITION = "ERR_INVALID_STATE_TRANSITION"       # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                             # 412

# --- facility / contract / ticket ---
ERR_FACILITY_NOT_ACTIVE = "ERR_FACILITY_NOT_ACTIVE"                 # 409
ERR_FACILITY_HAS_OPEN_OBLIGATIONS = "ERR_FACILITY_HAS_OPEN_OBLIGATIONS"  # 409
ERR_NO_ACTIVE_CONTRACT = "ERR_NO_ACTIVE_CONTRACT"                   # 409
ERR_CONTRACT_SUSPENDED = "ERR_CONTRACT_SUSPENDED"                   # 409
ERR_CONTRACT_NOT_EXPIRED = "ERR_CONTRACT_NOT_EXPIRED"               # 409
ERR_CONTRACT_TIER_INELIGIBLE = "ERR_CONTRACT_TIER_INELIGIBLE"       # 409

# --- compressor / maintenance ---
ERR_COMPRESSOR_NOT_DOWN = "ERR_COMPRESSOR_NOT_DOWN"                 # 409
ERR_DUPLICATE_ASSET_TAG = "ERR_DUPLICATE_ASSET_TAG"                 # 409
ERR_RUN_HOURS_REGRESSION = "ERR_RUN_HOURS_REGRESSION"               # 422
ERR_READING_EXCEEDS_LOGGED = "ERR_READING_EXCEEDS_LOGGED"           # 422
ERR_DUPLICATE_SCHEDULE_COMPONENT = "ERR_DUPLICATE_SCHEDULE_COMPONENT"  # 409

# --- demand profile / savings ---
ERR_MEASUREMENT_WINDOW_OVERLAP = "ERR_MEASUREMENT_WINDOW_OVERLAP"   # 409
ERR_PROFILE_NOT_LOCKED = "ERR_PROFILE_NOT_LOCKED"                   # 409
ERR_BASELINE_SUPERSEDED = "ERR_BASELINE_SUPERSEDED"                 # 409
ERR_RETROFIT_STALE = "ERR_RETROFIT_STALE"                           # 409
ERR_RETROFIT_NOT_APPROVED = "ERR_RETROFIT_NOT_APPROVED"             # 409
ERR_RETROFIT_NOT_ACCEPTED = "ERR_RETROFIT_NOT_ACCEPTED"             # 409
ERR_POST_WINDOW_BEFORE_ACCEPTANCE = "ERR_POST_WINDOW_BEFORE_ACCEPTANCE"  # 409
ERR_SEQUENCE_COMPRESSOR_INVALID = "ERR_SEQUENCE_COMPRESSOR_INVALID"  # 422
ERR_FACILITY_MISMATCH = "ERR_FACILITY_MISMATCH"                     # 409

# --- leak survey / repair ---
ERR_EMPTY_SURVEY = "ERR_EMPTY_SURVEY"                               # 422
ERR_SURVEY_NOT_VERIFIED = "ERR_SURVEY_NOT_VERIFIED"                 # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"             # 403
ERR_REPAIR_BUDGET_EXCEEDED = "ERR_REPAIR_BUDGET_EXCEEDED"           # 409

# --- rental ---
ERR_NO_RENTAL_ASSET_AVAILABLE = "ERR_NO_RENTAL_ASSET_AVAILABLE"     # 409
ERR_RENTAL_ASSET_UNAVAILABLE = "ERR_RENTAL_ASSET_UNAVAILABLE"       # 409
ERR_RENTAL_DATE_RANGE_INVALID = "ERR_RENTAL_DATE_RANGE_INVALID"     # 422
ERR_DUPLICATE_FLEET_TAG = "ERR_DUPLICATE_FLEET_TAG"                 # 409

# --- guarantee / credit ---
ERR_MEASUREMENT_INCOMPLETE = "ERR_MEASUREMENT_INCOMPLETE"           # 409
ERR_POSTURE_NOT_NORMAL = "ERR_POSTURE_NOT_NORMAL"                   # 409
ERR_DISPUTE_OPEN_PAYOUT_FROZEN = "ERR_DISPUTE_OPEN_PAYOUT_FROZEN"   # 409
ERR_CERTIFICATE_EXISTS = "ERR_CERTIFICATE_EXISTS"                   # 409
ERR_CREDIT_NOT_EXPIRED = "ERR_CREDIT_NOT_EXPIRED"                   # 409


def err(error_id, status, message):
    return ApiError(error_id, status, message)


def not_found(message="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, message)


def invalid_request(message):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def invalid_state(message):
    return ApiError(ERR_INVALID_STATE_TRANSITION, 409, message)


def conflict(error_id, message):
    return ApiError(error_id, 409, message)


def unprocessable(error_id, message):
    return ApiError(error_id, 422, message)
