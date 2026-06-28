"""Error classes and error-id constants (PRD §5 Error Code Catalogue)."""


class ApiError(Exception):
    """Carries error_id, message, http_status for the standard error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (id -> http status). PRD §5.
ERR_MISSING_OR_INVALID_USER_CONTEXT = "ERR_MISSING_OR_INVALID_USER_CONTEXT"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_NOT_RENDERING_PROVIDER = "ERR_NOT_RENDERING_PROVIDER"
ERR_ENCOUNTER_BAD_STATE = "ERR_ENCOUNTER_BAD_STATE"
ERR_PA_BAD_STATE = "ERR_PA_BAD_STATE"
ERR_RX_BAD_STATE = "ERR_RX_BAD_STATE"
ERR_LAB_ORDER_BAD_STATE = "ERR_LAB_ORDER_BAD_STATE"
ERR_DME_BAD_STATE = "ERR_DME_BAD_STATE"
ERR_IMAGING_BAD_STATE = "ERR_IMAGING_BAD_STATE"
ERR_RECALL_BAD_STATE = "ERR_RECALL_BAD_STATE"
ERR_PA_CATEGORY_MISMATCH = "ERR_PA_CATEGORY_MISMATCH"
ERR_PA_NOT_DRAWABLE = "ERR_PA_NOT_DRAWABLE"
ERR_PA_EXPIRED = "ERR_PA_EXPIRED"
ERR_PA_UNITS_EXCEEDED = "ERR_PA_UNITS_EXCEEDED"
ERR_PROVIDER_DOUBLE_BOOKED = "ERR_PROVIDER_DOUBLE_BOOKED"
ERR_MODALITY_DOUBLE_BOOKED = "ERR_MODALITY_DOUBLE_BOOKED"
ERR_PA_VERSION_STALE = "ERR_PA_VERSION_STALE"
ERR_MODALITY_VERSION_STALE = "ERR_MODALITY_VERSION_STALE"


# Convenience constructors -----------------------------------------------------

def missing_user_context(msg="Missing or invalid user context."):
    return ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT, 401, msg)


def forbidden_role(msg="Role not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Resource not found."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def fk_not_found(msg="Referenced resource not found."):
    return ApiError(ERR_FK_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)
