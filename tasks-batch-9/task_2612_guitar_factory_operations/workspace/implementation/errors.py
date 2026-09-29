"""Error catalogue and the ApiError exception (PRD section 5)."""

ERROR_STATUS = {
    # --- authn / authz ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SHOP_IDENTITY_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_MEASUREMENT_OWNER_MISMATCH": 403,
    # --- schema ---
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_WINDOW": 422,
    # --- not found ---
    "ERR_STORAGE_ROOM_NOT_FOUND": 404,
    "ERR_TONEWOOD_LOT_NOT_FOUND": 404,
    "ERR_BILLET_NOT_FOUND": 404,
    "ERR_COMPONENT_SPEC_NOT_FOUND": 404,
    "ERR_COMPONENT_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_STATION_RESERVATION_NOT_FOUND": 404,
    "ERR_OPTION_CATALOG_NOT_FOUND": 404,
    "ERR_BUILD_ORDER_NOT_FOUND": 404,
    "ERR_OPTION_SELECTION_NOT_FOUND": 404,
    "ERR_FINISH_RUN_NOT_FOUND": 404,
    "ERR_SETUP_INSPECTION_NOT_FOUND": 404,
    "ERR_REPAIR_SHOP_NOT_FOUND": 404,
    "ERR_WARRANTY_REGISTRATION_NOT_FOUND": 404,
    "ERR_EXPORT_SHIPMENT_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    # --- uniqueness ---
    "ERR_DUPLICATE_CODE": 409,
    "ERR_WARRANTY_ALREADY_REGISTERED": 409,
    # --- state ---
    "ERR_ROOM_STATE_INVALID": 409,
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_BILLET_STATE_INVALID": 409,
    "ERR_COMPONENT_STATE_INVALID": 409,
    "ERR_RESERVATION_STATE_INVALID": 409,
    "ERR_OPTION_SELECTION_STATE_INVALID": 409,
    "ERR_FINISH_RUN_STATE_INVALID": 409,
    "ERR_INSPECTION_STATE_INVALID": 409,
    "ERR_SHOP_STATE_INVALID": 409,
    "ERR_SHIPMENT_STATE_INVALID": 409,
    "ERR_BUILD_STAGE_INVALID": 409,
    "ERR_COMMERCIAL_STATUS_INVALID": 409,
    "ERR_WARRANTY_STATE_INVALID": 409,
    # --- optimistic concurrency ---
    "ERR_STALE_VERSION": 412,
    # --- climate ---
    "ERR_ROOM_CLIMATE_OUT_OF_SPEC": 409,
    "ERR_ROOM_QUARANTINED": 409,
    # --- compliance ---
    "ERR_CITES_PERMIT_UNVERIFIED": 409,
    "ERR_CITES_PERMIT_MISSING": 409,
    "ERR_PROTECTED_SPECIES_QUARANTINED": 409,
    "ERR_COMPLIANCE_HOLD_ACTIVE": 409,
    # --- referential compatibility ---
    "ERR_GRADE_BELOW_MINIMUM": 422,
    "ERR_SPECIES_NOT_PERMITTED": 422,
    "ERR_STATION_TYPE_MISMATCH": 422,
    "ERR_RESERVATION_COMPONENT_MISMATCH": 422,
    "ERR_OPTION_FINISH_MISMATCH": 422,
    "ERR_OPTION_INCOMPATIBLE": 409,
    "ERR_BOOTH_ROOM_TYPE_INVALID": 422,
    "ERR_SERIAL_MISMATCH": 422,
    # --- cross-entity state ---
    "ERR_INSPECTION_NOT_SIGNED": 409,
    "ERR_LOT_NOT_RELEASED": 409,
    "ERR_COMPONENTS_NOT_ACCEPTED": 409,
    "ERR_COMPONENT_IN_FLIGHT": 409,
    "ERR_SHOP_NOT_AUTHORIZED": 409,
    "ERR_OPTIONS_NOT_SELECTED": 409,
    "ERR_INSPECTION_ROUND_OPEN": 409,
    "ERR_CURE_NOT_COMPLETE": 409,
    "ERR_REWORK_NOT_PERMITTED": 409,
    # --- windows / capacity ---
    "ERR_STATION_WINDOW_CONFLICT": 409,
    "ERR_BOOTH_FINISH_INCOMPATIBLE": 409,
    "ERR_BOOTH_CAPACITY_EXCEEDED": 409,
    # --- physical bands ---
    "ERR_MOISTURE_OUT_OF_BAND": 409,
    "ERR_THICKNESS_OUT_OF_TOLERANCE": 409,
    # --- quantity / ceilings / money ---
    "ERR_INSUFFICIENT_BOARD_FEET": 409,
    "ERR_MAX_REWORK_EXCEEDED": 409,
    "ERR_DEPOSIT_INSUFFICIENT": 402,
    "ERR_SERIAL_ALREADY_ASSIGNED": 409,
    "ERR_NO_ELIGIBLE_BUILD_ORDER": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").lower()


def fail(error_id, message=None):
    raise ApiError(error_id, message)
