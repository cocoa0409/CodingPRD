"""Error catalogue (PRD section 5) and the exception that carries it."""

ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 400,
    "ERR_PRODUCTION_RESOURCE_NOT_FOUND": 404,
    "ERR_PACKAGING_RESOURCE_NOT_FOUND": 404,
    "ERR_COMMERCIAL_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SCOBY_GENERATION_CAP": 422,
    "ERR_SCOBY_VITALITY_TOO_LOW": 422,
    "ERR_VESSEL_UNAVAILABLE": 409,
    "ERR_VESSEL_CIP_EXPIRED": 422,
    "ERR_VESSEL_CAPACITY_EXCEEDED": 422,
    "ERR_INGREDIENT_EXPIRED": 422,
    "ERR_PH_WINDOW_MISSED": 422,
    "ERR_LABEL_STALE": 409,
    "ERR_LABEL_CLASS_MISMATCH": 422,
    "ERR_ABV_CLASS_DIVERGENCE": 422,
    "ERR_BLEND_RULE_VIOLATION": 422,
    "ERR_INSUFFICIENT_BATCH_VOLUME": 422,
    "ERR_LOT_HOLD_PERIOD": 422,
    "ERR_QUARANTINE_CLEARANCE_CAP": 422,
    "ERR_INSUFFICIENT_LOT_UNITS": 422,
    "ERR_SHELF_LIFE_TOO_SHORT": 422,
    "ERR_KEG_RETAP_BUFFER": 422,
    "ERR_INSUFFICIENT_KEG_VOLUME": 422,
    "ERR_GROWLER_INSPECTION_REQUIRED": 422,
    "ERR_AGE_VERIFICATION_REQUIRED": 403,
    "ERR_ALCOHOLIC_CHANNEL_RESTRICTED": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_SELF_DIST_CEILING_EXCEEDED": 422,
    "ERR_SUBSCRIPTION_SKIP_CAP": 422,
    "ERR_PAUSE_WINDOW_CONFLICT": 409,
}

_DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, empty or name an unknown role.",
    "ERR_UNAUTHORIZED": "The acting role may not perform this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not perform this step.",
    "ERR_VALIDATION": "The request is not valid.",
    "ERR_PRODUCTION_RESOURCE_NOT_FOUND": "The referenced production resource does not exist.",
    "ERR_PACKAGING_RESOURCE_NOT_FOUND": "The referenced packaging resource does not exist.",
    "ERR_COMMERCIAL_RESOURCE_NOT_FOUND": "The referenced commercial resource does not exist.",
    "ERR_INVALID_STATE": "The resource is not in a state that allows this operation.",
    "ERR_STALE_VERSION": "The supplied version token does not match the current version.",
}


class ApiError(Exception):
    """A domain refusal carrying its catalogue identifier."""

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGE.get(
            error_id, "The request could not be completed."
        )
