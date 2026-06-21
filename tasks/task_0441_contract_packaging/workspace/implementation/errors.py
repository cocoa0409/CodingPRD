"""Error classes and error ID constants.

Every error_id and HTTP status here is read verbatim from SCAFFOLD.yaml §1.6
and PRD §5.
"""


class ApiError(Exception):
    """Carries error_id, message, and http_status for the response envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (SCAFFOLD §1.6 / PRD §5) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"               # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                     # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                           # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"               # 400
ERR_DUPLICATE_CODE = "ERR_DUPLICATE_CODE"                 # 409
ERR_DUPLICATE_SKU = "ERR_DUPLICATE_SKU"                   # 409
ERR_INVALID_QUANTITY = "ERR_INVALID_QUANTITY"             # 422
ERR_INVALID_ENUM = "ERR_INVALID_ENUM"                     # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"                   # 409
ERR_RECIPE_NOT_APPROVED = "ERR_RECIPE_NOT_APPROVED"       # 409
ERR_ALLERGEN_CHANGEOVER_REQUIRED = "ERR_ALLERGEN_CHANGEOVER_REQUIRED"  # 409
ERR_LOT_EXPIRED = "ERR_LOT_EXPIRED"                       # 409
ERR_INSUFFICIENT_MATERIAL = "ERR_INSUFFICIENT_MATERIAL"   # 409
ERR_OVERRUN_EXCEEDED = "ERR_OVERRUN_EXCEEDED"             # 422
ERR_LINE_OVERLAP = "ERR_LINE_OVERLAP"                     # 409
ERR_CREW_OVERLAP = "ERR_CREW_OVERLAP"                     # 409
ERR_QA_REJECT_RATE_EXCEEDED = "ERR_QA_REJECT_RATE_EXCEEDED"  # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                   # 412


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Missing required field, malformed body, or wrong type"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def duplicate_code(msg="Customer code already used by another customer"):
    return ApiError(ERR_DUPLICATE_CODE, 409, msg)


def duplicate_sku(msg="Component sku already used within the same customer"):
    return ApiError(ERR_DUPLICATE_SKU, 409, msg)


def invalid_quantity(msg="A quantity/weight/tolerance/shelf-life field violates its constraint"):
    return ApiError(ERR_INVALID_QUANTITY, 422, msg)


def invalid_enum(msg="An enum field holds a value outside its allowed set"):
    return ApiError(ERR_INVALID_ENUM, 422, msg)


def invalid_state(msg="Requested transition not defined from the entity's current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def recipe_not_approved(msg="Recipe not APPROVED, or sampling a run not RUNNING/PENDING_QA"):
    return ApiError(ERR_RECIPE_NOT_APPROVED, 409, msg)


def allergen_changeover_required(msg="Line carries allergen residue not in the recipe profile"):
    return ApiError(ERR_ALLERGEN_CHANGEOVER_REQUIRED, 409, msg)


def lot_expired(msg="A component lot needed for consumption is expired at the logical clock"):
    return ApiError(ERR_LOT_EXPIRED, 409, msg)


def insufficient_material(msg="Available non-expired remaining_qty cannot cover required_qty"):
    return ApiError(ERR_INSUFFICIENT_MATERIAL, 409, msg)


def overrun_exceeded(msg="Actual good+scrapped units exceed the over-run ceiling"):
    return ApiError(ERR_OVERRUN_EXCEEDED, 422, msg)


def line_overlap(msg="Run window overlaps a non-terminal run on the same line"):
    return ApiError(ERR_LINE_OVERLAP, 409, msg)


def crew_overlap(msg="Run buffered window overlaps a non-terminal run on the same crew"):
    return ApiError(ERR_CREW_OVERLAP, 409, msg)


def qa_reject_rate_exceeded(msg="Release attempted with no samples or reject_rate above maximum"):
    return ApiError(ERR_QA_REJECT_RATE_EXCEEDED, 409, msg)


def stale_version(msg="expected version does not equal the parent's current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)
