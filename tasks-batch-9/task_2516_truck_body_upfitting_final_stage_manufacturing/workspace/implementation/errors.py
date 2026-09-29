"""Error catalog for the Truck Body Upfitting & Final Stage Manufacturing API.

Every error identifier and its HTTP status is taken verbatim from PRD section 5.
"""

# error_id -> http_status
ERROR_CATALOG = {
    # --- authentication / authorization -----------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CUSTOMER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request shape ----------------------------------------------------
    "ERR_INVALID_REQUEST": 422,
    # --- existence --------------------------------------------------------
    "ERR_CHASSIS_MODEL_NOT_FOUND": 404,
    "ERR_BODY_SPEC_NOT_FOUND": 404,
    "ERR_EQUIPMENT_SPEC_NOT_FOUND": 404,
    "ERR_WORK_BAY_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_BUILD_CONFIGURATION_NOT_FOUND": 404,
    "ERR_CHASSIS_NOT_FOUND": 404,
    "ERR_UPFIT_ORDER_NOT_FOUND": 404,
    "ERR_EQUIPMENT_INSTALLATION_NOT_FOUND": 404,
    "ERR_ELECTRICAL_INTERFACE_NOT_FOUND": 404,
    "ERR_BUILD_SLOT_NOT_FOUND": 404,
    "ERR_WEIGHT_CERTIFICATION_NOT_FOUND": 404,
    "ERR_COMPLIANCE_LABEL_NOT_FOUND": 404,
    "ERR_WARRANTY_CLAIM_NOT_FOUND": 404,
    # --- optimistic concurrency ------------------------------------------
    "ERR_STALE_UPFIT_ORDER_VERSION": 412,
    "ERR_STALE_CHASSIS_VERSION": 412,
    # --- uniqueness -------------------------------------------------------
    "ERR_DUPLICATE_VIN": 409,
    "ERR_DUPLICATE_CONFIG_CODE": 409,
    "ERR_DUPLICATE_ORDER_NUMBER": 409,
    "ERR_DUPLICATE_CLAIM_NUMBER": 409,
    # --- state preconditions ---------------------------------------------
    "ERR_ORDER_INVALID_STATE": 409,
    "ERR_CHASSIS_INVALID_STATE": 409,
    "ERR_INSTALLATION_INVALID_STATE": 409,
    "ERR_INTERFACE_INVALID_STATE": 409,
    "ERR_SLOT_INVALID_STATE": 409,
    "ERR_CERTIFICATION_INVALID_STATE": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
    "ERR_CONFIG_INVALID_STATE": 409,
    "ERR_LABEL_ALREADY_SUPERSEDED": 409,
    # --- regulatory weight safety ----------------------------------------
    "ERR_GVWR_EXCEEDED": 422,
    "ERR_REAR_GAWR_EXCEEDED": 422,
    "ERR_FRONT_GAWR_EXCEEDED": 422,
    "ERR_PAYLOAD_SHORTFALL": 422,
    "ERR_MEASURED_CERTIFICATION_REQUIRED": 409,
    # --- temporal feasibility --------------------------------------------
    "ERR_IN_SERVICE_DATE_INFEASIBLE": 422,
    "ERR_CHASSIS_OCCUPANCY_CONFLICT": 409,
    "ERR_BAY_CAPACITY_CONFLICT": 409,
    "ERR_CHASSIS_NOT_AVAILABLE_BY_SLOT_START": 422,
    "ERR_SLOT_DATE_RANGE_INVALID": 422,
    # --- body builder book constraints -----------------------------------
    "ERR_CAB_TO_AXLE_INSUFFICIENT": 422,
    "ERR_WHEELBASE_INSUFFICIENT": 422,
    "ERR_AUX_ELECTRICAL_LOAD_EXCEEDED": 422,
    "ERR_PTO_FLOW_CAPACITY_EXCEEDED": 422,
    "ERR_PTO_NOT_PROVISIONED": 422,
    "ERR_HYDRAULIC_CIRCUIT_REQUIRED": 422,
    "ERR_HYDRAULIC_DEFICIT_UNRESOLVED": 409,
    "ERR_CHASSIS_WARRANTY_VOIDING_INTERFACE": 422,
    "ERR_CAN_GATEWAY_REQUIRED": 422,
    "ERR_CONFIG_NOT_PUBLISHED": 409,
    "ERR_BAY_BODY_TYPE_UNSUPPORTED": 422,
    "ERR_NON_STANDARD_POOL_EQUIPMENT": 422,
    "ERR_BODY_ALREADY_INSTALLED": 409,
    "ERR_CHASSIS_MODEL_MISMATCH": 422,
    "ERR_MOUNT_ZONE_CONFLICT": 409,
    "ERR_HYDRAULIC_SOURCE_MISSING": 422,
    # --- referential integrity -------------------------------------------
    "ERR_CERTIFICATION_ORDER_MISMATCH": 422,
    "ERR_CERTIFICATION_NOT_APPROVED": 409,
    "ERR_LABEL_ALREADY_ACTIVE": 409,
    "ERR_CHASSIS_ALREADY_ALLOCATED": 409,
    # --- fiscal -----------------------------------------------------------
    "ERR_WARRANTY_BUDGET_EXCEEDED": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or malformed authentication headers.",
    "ERR_UNAUTHORIZED": "The caller's role may not perform this operation.",
    "ERR_CUSTOMER_SCOPE_VIOLATION": "Customer callers may only reach their own records.",
    "ERR_SEGREGATION_OF_DUTIES": "The same user may not perform both halves of this control.",
    "ERR_INVALID_REQUEST": "The request payload is malformed or out of range.",
    "ERR_STALE_UPFIT_ORDER_VERSION": "The supplied upfit order version is stale.",
    "ERR_STALE_CHASSIS_VERSION": "The supplied chassis version is stale.",
    "ERR_WARRANTY_BUDGET_EXCEEDED": "The order's upfitter warranty liability cap would be exceeded.",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with a catalog error."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_CATALOG.get(error_id, 422)
        if message is None:
            message = DEFAULT_MESSAGES.get(error_id)
        if message is None:
            message = error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        self.message = message


def api_error(error_id, message=None):
    return ApiError(error_id, message)
