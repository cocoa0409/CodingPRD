"""Error catalogue (PRD §5 / scaffold §1.6). HTTP statuses are read from the
catalogue, never assumed."""

ERROR_HTTP = {
    # -- auth ---------------------------------------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ACTOR_NOT_OWNER": 403,
    "ERR_PERMIT_TRACK_ROLE_MISMATCH": 403,
    "ERR_SAME_ACTOR_REVIEW": 403,
    "ERR_INVALID_REQUEST": 400,
    # -- existence ----------------------------------------------------------
    "ERR_FACTORY_NOT_FOUND": 404,
    "ERR_AGENCY_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_DESIGN_PACKAGE_NOT_FOUND": 404,
    "ERR_MODULE_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_DEFECT_CLAIM_NOT_FOUND": 404,
    "ERR_DRAW_NOT_FOUND": 404,
    # -- optimistic concurrency --------------------------------------------
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_SHIPMENT_VERSION": 412,
    # -- state --------------------------------------------------------------
    "ERR_DESIGN_REVIEW_IN_FLIGHT": 409,
    "ERR_DESIGN_NOT_SUBMITTABLE": 409,
    "ERR_DESIGN_NOT_IN_REVIEW": 409,
    "ERR_DRAW_NOT_DRAFT": 409,
    "ERR_DRAW_NOT_CERTIFIED": 409,
    "ERR_MODULE_NOT_PLANNED": 409,
    "ERR_MODULE_NOT_SLOTTED": 409,
    "ERR_MODULE_NOT_ON_LINE": 409,
    "ERR_MODULE_NOT_READY_TO_SET": 409,
    "ERR_MODULE_NOT_SET": 409,
    "ERR_FIELD_SCOPE_NOT_SIGNED_OFF": 422,
    "ERR_SHIPMENT_NOT_LOADABLE": 409,
    "ERR_SURVEY_NOT_PENDING": 409,
    "ERR_SHIPMENT_NOT_PERMITTED": 409,
    "ERR_SHIPMENT_NOT_DISPATCHED": 409,
    "ERR_SHIPMENT_TERMINAL": 409,
    "ERR_PERMIT_ALREADY_DECIDED": 409,
    "ERR_INSPECTION_NOT_PENDING": 409,
    "ERR_HOLD_NOT_ACTIVE": 409,
    "ERR_CLAIM_NOT_ADJUDICABLE": 409,
    "ERR_CLAIM_NOT_ADJUDICATED": 409,
    "ERR_DISPUTE_ROUND_LIMIT": 409,
    # -- safety / regulatory ------------------------------------------------
    "ERR_FACTORY_LINE_NOT_RUNNING": 409,
    "ERR_PICK_RADIUS_OFF_CHART": 422,
    "ERR_CRANE_CAPACITY_EXCEEDED": 422,
    "ERR_WEATHER_EXPOSURE_LIMIT": 409,
    "ERR_SET_NOT_PERMITTED": 409,
    "ERR_QC_HOLD_BLOCKS_OPERATION": 409,
    "ERR_QC_NOT_RELEASED": 409,
    # -- constraint satisfaction -------------------------------------------
    "ERR_SET_SEQUENCE_VIOLATION": 409,
    "ERR_LINE_CAPACITY_EXCEEDED": 409,
    "ERR_CRANE_WINDOW_CONFLICT": 409,
    "ERR_MODULE_ALREADY_LOADED": 409,
    "ERR_ENVELOPE_EXCEEDS_ROUTE_LIMIT": 422,
    "ERR_QC_STAGE_OUT_OF_ORDER": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_DUPLICATE_MODULE_CODE": 409,
    "ERR_ESCORT_NOT_CONFIRMED": 422,
    # -- temporal -----------------------------------------------------------
    "ERR_LINE_SLOT_IN_PAST": 422,
    "ERR_LINE_SLOT_OUTSIDE_SHIFT": 422,
    "ERR_PICK_WINDOW_INVALID": 422,
    "ERR_TRANSPORT_PERMIT_EXPIRED": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # -- referential / compliance ------------------------------------------
    "ERR_AGENCY_NOT_ACCREDITED": 422,
    "ERR_AGENCY_JURISDICTION_MISMATCH": 422,
    "ERR_PLAN_REVIEW_PREREQUISITE": 409,
    "ERR_NO_FROZEN_PACKAGE": 409,
    "ERR_PINNED_PACKAGE_MISMATCH": 409,
    "ERR_INVALID_SUPERSESSION": 422,
    "ERR_FACTORY_COMPATIBILITY_TOO_LOW": 422,
    "ERR_CROSS_AGGREGATE_MISMATCH": 422,
    "ERR_SHIPMENT_PROJECT_MISMATCH": 409,
    # -- fiscal -------------------------------------------------------------
    "ERR_CONTRACT_BALANCE_EXCEEDED": 422,
    "ERR_NO_CERTIFIABLE_WIP": 422,
    "ERR_DRAW_SEQUENCE_GAP": 409,
}


class ApiError(Exception):
    """Carries the scaffold error_id, a human message and the catalogue status."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
