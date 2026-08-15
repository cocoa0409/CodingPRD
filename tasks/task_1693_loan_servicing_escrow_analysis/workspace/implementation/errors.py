"""Error classes and error ID constants (from SCAFFOLD.yaml error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Auth ---
ERR_AUTH_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"   # 400
ERR_FORBIDDEN = "ERR_FORBIDDEN_FOR_ROLE"                         # 403
ERR_NOT_OWNER = "ERR_BORROWER_NOT_OWNER"                         # 403
# --- Existence ---
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                  # 404
ERR_REF_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"                    # 422
# --- Request shape ---
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                      # 400
ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"                        # 422
# --- Concurrency ---
ERR_STALE_VERSION = "ERR_STALE_VERSION"                          # 412
# --- State ---
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"                    # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE_TRANSITION"               # 409
ERR_ON_HOLD = "ERR_ACCOUNT_ON_HOLD"                              # 409
ERR_LOAN_NOT_ACTIVE = "ERR_LOAN_NOT_ACTIVE"                      # 409
# --- Compliance / safety ---
ERR_SOD = "ERR_SOD_VIOLATION"                                    # 409
ERR_NOTICE_WINDOW = "ERR_NOTICE_WINDOW_NOT_MET"                  # 409
ERR_REMINDER_EARLY = "ERR_REMINDER_TOO_EARLY"                    # 409
ERR_ACTIVE_COVERAGE = "ERR_ACTIVE_COVERAGE_EXISTS"               # 409
# --- Temporal ---
ERR_RELEASE_EARLY = "ERR_RELEASE_TOO_EARLY"                      # 409
ERR_EFFECTIVE_NOT_REACHED = "ERR_EFFECTIVE_DATE_NOT_REACHED"     # 409
ERR_EXTENSION_PASSED = "ERR_EXTENSION_WINDOW_PASSED"             # 409
ERR_PROJECTION_START = "ERR_PROJECTION_START_INVALID"            # 422
# --- Constraint / duplicates ---
ERR_DUP_LOAN_NUMBER = "ERR_DUPLICATE_LOAN_NUMBER"                # 409
ERR_ESCROW_EXISTS = "ERR_ESCROW_ACCOUNT_EXISTS"                  # 409
ERR_DUP_LINE_ITEM = "ERR_DUPLICATE_LINE_ITEM_TYPE"               # 409
ERR_DUP_CASE = "ERR_DUPLICATE_ACTIVE_CASE"                       # 409
ERR_COVERAGE_OVERLAP = "ERR_COVERAGE_OVERLAP"                    # 409
ERR_WINDOW_OVERLAP = "ERR_ANALYSIS_WINDOW_OVERLAP"               # 409
# --- Referential ---
ERR_PAYEE_NOT_VERIFIED = "ERR_PAYEE_NOT_VERIFIED"                # 409
ERR_UNRESOLVED_CASE = "ERR_UNRESOLVED_ERROR_CASE"                # 409
ERR_ADVANCE_OUTSTANDING = "ERR_ADVANCE_OUTSTANDING"              # 409
ERR_ESCROW_NOT_ACTIVE = "ERR_ESCROW_NOT_ACTIVE"                  # 409
# --- Fiscal ---
ERR_ADVANCE_CAP = "ERR_ADVANCE_CAP_EXCEEDED"                     # 422
ERR_RECOVERY_EXCEEDS = "ERR_RECOVERY_EXCEEDS_OUTSTANDING"        # 422
ERR_OPTION_REQUIRED = "ERR_SHORTAGE_OPTION_REQUIRED"             # 422
ERR_OPTION_N_A = "ERR_SHORTAGE_OPTION_NOT_APPLICABLE"            # 422
ERR_LUMP_SUM_MISSING = "ERR_SHORTAGE_LUMP_SUM_MISSING"           # 422
ERR_SPREAD_MANDATORY = "ERR_DEFICIENCY_SPREAD_MANDATORY"         # 422


def err(error_id, status, message):
    return ApiError(error_id, status, message)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def bad_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)
