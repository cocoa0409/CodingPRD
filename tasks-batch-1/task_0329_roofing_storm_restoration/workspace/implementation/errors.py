"""Error catalog and ApiError exception class.

Every error_id / http_status pair is taken verbatim from the PRD §5 error
catalogue and SCAFFOLD errors table.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---- Auth / existence ----
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"                # 404

# ---- Body validation ----
ERR_MISSING_FIELD = "ERR_MISSING_FIELD"              # 400
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_VALIDATION = "ERR_VALIDATION"                    # 400 (pagination bounds)

# ---- State ----
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_ALREADY_CONTRACTED = "ERR_ALREADY_CONTRACTED"    # 409

# ---- Cross-entity state preconditions ----
ERR_NO_PASSED_ASSESSMENT = "ERR_NO_PASSED_ASSESSMENT"        # 409
ERR_NO_FINALIZED_ESTIMATE = "ERR_NO_FINALIZED_ESTIMATE"     # 409
ERR_EMPTY_ESTIMATE = "ERR_EMPTY_ESTIMATE"                   # 409
ERR_SEVERITY_REQUIRED = "ERR_SEVERITY_REQUIRED"             # 422
ERR_MATERIALS_NOT_DELIVERED = "ERR_MATERIALS_NOT_DELIVERED" # 409
ERR_PERMIT_NOT_ISSUED = "ERR_PERMIT_NOT_ISSUED"             # 409
ERR_JOB_NOT_IN_PRODUCTION = "ERR_JOB_NOT_IN_PRODUCTION"     # 409
ERR_CREW_INACTIVE = "ERR_CREW_INACTIVE"                     # 409
ERR_JOB_NOT_COMPLETED = "ERR_JOB_NOT_COMPLETED"             # 409

# ---- Temporal ----
ERR_CREW_DOUBLE_BOOKED = "ERR_CREW_DOUBLE_BOOKED"                 # 409
ERR_INSPECTION_BUFFER_CONFLICT = "ERR_INSPECTION_BUFFER_CONFLICT" # 409
ERR_PERMIT_FINAL_NEEDS_PERMIT = "ERR_PERMIT_FINAL_NEEDS_PERMIT"   # 422

# ---- Fiscal ----
ERR_PCT_NOT_INCREASING = "ERR_PCT_NOT_INCREASING"           # 409
ERR_PCT_OUT_OF_RANGE = "ERR_PCT_OUT_OF_RANGE"               # 422
ERR_CONTRACT_BELOW_DISBURSED = "ERR_CONTRACT_BELOW_DISBURSED"  # 409

# ---- Completion ----
ERR_FINAL_DRAW_MISSING = "ERR_FINAL_DRAW_MISSING"           # 409
ERR_FINAL_INSPECTION_MISSING = "ERR_FINAL_INSPECTION_MISSING"  # 409
ERR_OPEN_CHANGE_ORDER = "ERR_OPEN_CHANGE_ORDER"            # 409

# ---- Warranty / OCC ----
ERR_WARRANTY_NOT_EXPIRED = "ERR_WARRANTY_NOT_EXPIRED"      # 409
ERR_STALE_JOB_VERSION = "ERR_STALE_JOB_VERSION"           # 412


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)
