"""Error catalogue and the ApiError exception (PRD section 5)."""

ERROR_STATUS = {
    # --- authentication and authorization ---
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_PLANT_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- not found ---
    "ERR_PLANT_NOT_FOUND": 404,
    "ERR_CLAY_PIT_NOT_FOUND": 404,
    "ERR_FORMULATION_NOT_FOUND": 404,
    "ERR_KILN_NOT_FOUND": 404,
    "ERR_KILN_CAR_NOT_FOUND": 404,
    "ERR_PRODUCTION_RUN_NOT_FOUND": 404,
    "ERR_KILN_RUN_NOT_FOUND": 404,
    "ERR_FIRED_LOT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_BLEND_NOT_FOUND": 404,
    "ERR_SAMPLE_PANEL_NOT_FOUND": 404,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 400,
    # --- optimistic concurrency ---
    "ERR_STALE_VERSION": 412,
    # --- state preconditions ---
    "ERR_PLANT_IDLED": 409,
    "ERR_CLAY_PIT_SUSPENDED": 409,
    "ERR_FORMULATION_NOT_DRAFT": 409,
    "ERR_PRODUCTION_RUN_STATE_INVALID": 409,
    "ERR_KILN_CAR_NOT_IDLE": 409,
    "ERR_KILN_RUN_STATE_INVALID": 409,
    "ERR_FIRED_LOT_UNAVAILABLE": 409,
    "ERR_LOT_QUARANTINED": 409,
    "ERR_BLEND_NOT_DRAFT": 409,
    "ERR_BLEND_NOT_COMPOSED": 409,
    "ERR_ORDER_STATE_INVALID": 409,
    "ERR_PANEL_STATE_INVALID": 409,
    # --- business safety and quality ---
    "ERR_PANEL_NOT_APPROVED": 422,
    "ERR_PANEL_APPROVAL_EXPIRED": 422,
    "ERR_DYE_LOT_MISMATCH": 422,
    "ERR_PANEL_TOLERANCE_EXCEEDED": 422,
    "ERR_COLOR_RANGE_SPAN_EXCEEDED": 422,
    "ERR_DURABILITY_GRADE_NOT_MET": 422,
    # --- cross-entity referential ---
    "ERR_FORMULATION_NOT_QUALIFIED": 409,
    "ERR_BLEND_NOT_CERTIFIED": 409,
    "ERR_UNLOADING_EQUIPMENT_UNAVAILABLE": 422,
    "ERR_UNLOADING_EQUIPMENT_MISMATCH": 422,
    "ERR_PIT_PLANT_MISMATCH": 422,
    "ERR_LOT_ATTRIBUTE_MISMATCH": 422,
    # --- constraints ---
    "ERR_DUPLICATE_CODE": 409,
    "ERR_COMPONENT_SHARE_TOTAL_INVALID": 422,
    "ERR_INVALID_KILN_POSITION": 422,
    "ERR_KILN_POSITION_OCCUPIED": 409,
    "ERR_KILN_CAR_CAPACITY_EXCEEDED": 422,
    "ERR_BLEND_OVER_ALLOCATION": 422,
    "ERR_PANEL_REVISION_LIMIT": 409,
    # --- temporal ---
    "ERR_KILN_WINDOW_CONFLICT": 409,
    "ERR_KILN_CAR_OCCUPIED": 409,
    # --- fiscal and capacity ---
    "ERR_NO_PLANT_IN_MARKET_RADIUS": 422,
    "ERR_CLAY_RESERVE_INSUFFICIENT": 422,
    "ERR_INSUFFICIENT_BLEND_INVENTORY": 422,
    "ERR_PALLET_COUNT_INSUFFICIENT": 422,
    "ERR_BAND_COUNT_INSUFFICIENT": 422,
}


class ApiError(Exception):
    """A single rejection carrying exactly one error_id."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words
