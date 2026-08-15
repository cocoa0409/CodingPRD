"""Error catalog (PRD section 5 / SCAFFOLD 1.6) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Auth
ERR_MISSING_CONTEXT = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"      # 400
ERR_FORBIDDEN = "ERR_INSUFFICIENT_PERMISSIONS"                          # 403

# Existence
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                         # 404

# Payload shape
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                             # 400

# Concurrency
ERR_STALE_VERSION = "ERR_STALE_VERSION"                                 # 412

# State machine
ERR_INVALID_STATE = "ERR_INVALID_STATE"                                 # 409

# Segregation of duties
ERR_SOD = "ERR_SEGREGATION_OF_DUTIES_VIOLATION"                         # 403

# Charity screening
ERR_SCREENING_NOT_CURRENT = "ERR_SCREENING_NOT_CURRENT"                 # 409
ERR_CHARITY_BLOCKS = "ERR_CHARITY_ELIGIBLE_BLOCKS_PLACEMENT"            # 409
ERR_ACCOUNT_NOT_SCREENABLE = "ERR_ACCOUNT_NOT_SCREENABLE"               # 409

# Statement cycle / aging prerequisites
ERR_NOT_STATEMENT_ELIGIBLE = "ERR_ACCOUNT_NOT_STATEMENT_ELIGIBLE"       # 409
ERR_NOT_EARLY_OUT_BUCKET = "ERR_ACCOUNT_NOT_IN_EARLY_OUT_BUCKET"        # 409
ERR_NOT_AGENCY_BUCKET = "ERR_ACCOUNT_NOT_IN_AGENCY_BUCKET"              # 409
ERR_INSUFFICIENT_STATEMENTS = "ERR_INSUFFICIENT_STATEMENT_CYCLE"        # 409
ERR_WRITE_OFF_BEFORE_120 = "ERR_WRITE_OFF_BEFORE_120_DAYS"              # 409

# Placement rules
ERR_ACTIVE_PLACEMENT_EXISTS = "ERR_ACTIVE_PLACEMENT_EXISTS"             # 409
ERR_RECALL_DEADLINE_PASSED = "ERR_RECALL_DEADLINE_PASSED"               # 409
ERR_RECALL_WINDOW_STILL_OPEN = "ERR_RECALL_WINDOW_STILL_OPEN"           # 409

# Disputes
ERR_OPEN_DISPUTE_BLOCKS_PLACEMENT = "ERR_OPEN_DISPUTE_BLOCKS_PLACEMENT"  # 409
ERR_OPEN_DISPUTE_BLOCKS_WRITE_OFF = "ERR_OPEN_DISPUTE_BLOCKS_WRITE_OFF"  # 409
ERR_DISPUTE_AMOUNT_INVALID = "ERR_DISPUTE_AMOUNT_INVALID"               # 422

# Payment plans
ERR_PLAN_BLOCKS_WRITE_OFF = "ERR_ACTIVE_PAYMENT_PLAN_BLOCKS_WRITE_OFF"  # 409
ERR_PLAN_NOT_IN_DEFAULT = "ERR_PLAN_NOT_IN_DEFAULT"                     # 409
ERR_CATCH_UP_REQUIRED = "ERR_CATCH_UP_PAYMENT_REQUIRED"                 # 422

# Recovery / fiscal
ERR_RECOVERY_FK_MISMATCH = "ERR_RECOVERY_FK_MISMATCH"                   # 400
ERR_RECOVERY_EXCEEDS_BALANCE = "ERR_RECOVERY_EXCEEDS_BALANCE"           # 422
ERR_PARTIAL_WRITE_OFF = "ERR_PARTIAL_WRITE_OFF_NOT_SUPPORTED"           # 422
ERR_INVALID_COST_REPORT_YEAR = "ERR_INVALID_COST_REPORT_YEAR"           # 422
ERR_REVERSAL_WINDOW_PASSED = "ERR_REVERSAL_WINDOW_PASSED"               # 409


def not_found(msg="resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def invalid_state(msg="resource is in a state that does not allow this transition"):
    return ApiError(ERR_INVALID_STATE, msg, 409)
