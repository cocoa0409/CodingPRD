"""Error catalogue (PRD section 5) and the exception type carrying it."""

# error_id -> HTTP status, verbatim from PRD section 5 / SCAFFOLD `errors`.
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_BUILDER_NOT_FOUND": 404,
    "ERR_CONFIGURATION_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_DESIGN_NOT_FOUND": 404,
    "ERR_DRAWING_PACKAGE_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_LOAD_NOT_FOUND": 404,
    "ERR_STALE_CONFIGURATION_VERSION": 412,
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_BUILDER_NOT_AUTHORIZED": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CONFIGURATION_NOT_LOCKED": 409,
    "ERR_DESIGN_NOT_APPROVED": 409,
    "ERR_DRAWINGS_NOT_SEALED": 409,
    "ERR_ORDER_NOT_RELEASED": 409,
    "ERR_LOT_NOT_COMPLETE": 409,
    "ERR_ORDER_HAS_ACTIVE_WORK": 409,
    "ERR_PRIMARY_FRAME_MEMBERS_MISSING": 422,
    "ERR_CONNECTION_DETAILS_INCOMPLETE": 422,
    "ERR_CONNECTION_CAPACITY_INSUFFICIENT": 422,
    "ERR_SEAL_LICENSE_STATE_MISMATCH": 422,
    "ERR_MARK_NOT_FOUND": 422,
    "ERR_LOAD_ITEM_STAGE_MISMATCH": 422,
    "ERR_PAINT_COLOR_MISMATCH": 422,
    "ERR_LOT_TYPE_LINE_MISMATCH": 422,
    "ERR_QUOTE_EXPIRED": 422,
    "ERR_INVALID_WINDOW_RANGE": 400,
    "ERR_LOT_WINDOW_IN_PAST": 422,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_TERRITORY_BUILDER_LIMIT": 409,
    "ERR_DUPLICATE_COMPONENT_MARK": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_DUPLICATE_MARK": 400,
    "ERR_MARK_ALREADY_ASSIGNED": 409,
    "ERR_LINE_WINDOW_CONFLICT": 409,
    "ERR_SITE_UNLOAD_CAPACITY_EXCEEDED": 409,
    "ERR_ERECTION_SEQUENCE_VIOLATION": 409,
    "ERR_ADJUSTMENT_LIMIT_EXCEEDED": 422,
    "ERR_BUILDER_CREDIT_EXCEEDED": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be recognised.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting builder does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The submitting engineer may not review the design.",
    "ERR_INVALID_REQUEST": "The request body or query string is invalid.",
    "ERR_INVALID_STATE_TRANSITION": "The resource is not in the state this transition requires.",
}


class ApiError(Exception):
    """Raised anywhere in a handler; converted to the error envelope by app.py."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_CATALOG.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        super().__init__(self.message)


def invalid(message="The request body or query string is invalid."):
    return ApiError("ERR_INVALID_REQUEST", message)
