"""Error catalog: every error_id mapped to its HTTP status."""


ERROR_STATUS = {
    # --- authentication / authorisation -------------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_INVALID_ROLE": 403,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_BREWER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request shape ------------------------------------------------------
    "ERR_INVALID_REQUEST": 400,
    # --- existence ----------------------------------------------------------
    "ERR_BREWER_NOT_FOUND": 404,
    "ERR_CROP_YEAR_PROGRAM_NOT_FOUND": 404,
    "ERR_HOP_VARIETY_NOT_FOUND": 404,
    "ERR_HOP_CONTRACT_NOT_FOUND": 404,
    "ERR_SUBSTITUTION_OFFER_NOT_FOUND": 404,
    "ERR_MALT_PRODUCT_NOT_FOUND": 404,
    "ERR_MALT_LOT_NOT_FOUND": 404,
    "ERR_YEAST_STRAIN_NOT_FOUND": 404,
    "ERR_BREWER_RECIPE_NOT_FOUND": 404,
    "ERR_YEAST_JOB_NOT_FOUND": 404,
    "ERR_SALES_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_COLD_STORAGE_ZONE_NOT_FOUND": 404,
    "ERR_COLD_CHAIN_SHIPMENT_NOT_FOUND": 404,
    # --- referential integrity ----------------------------------------------
    "ERR_CONTRACT_BREWER_MISMATCH": 422,
    "ERR_ITEM_REFERENCE_MISMATCH": 422,
    "ERR_STRAIN_RECIPE_MISMATCH": 422,
    # --- state --------------------------------------------------------------
    "ERR_PROGRAM_NOT_OPEN": 409,
    "ERR_INVALID_CONTRACT_STATE": 409,
    "ERR_INVALID_PROGRAM_STATE": 409,
    "ERR_INVALID_LOT_STATE": 409,
    "ERR_INVALID_JOB_STATE": 409,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_SHIPMENT_STATE": 409,
    "ERR_INVALID_OFFER_STATE": 409,
    # --- optimistic concurrency --------------------------------------------
    "ERR_STALE_HOP_CONTRACT_VERSION": 412,
    "ERR_STALE_SALES_ORDER_VERSION": 412,
    "ERR_STALE_BREWER_VERSION": 412,
    # --- operational gates --------------------------------------------------
    "ERR_COLD_CHAIN_NOT_CERTIFIED": 422,
    "ERR_MALT_LOT_NOT_RELEASED": 409,
    "ERR_YEAST_NOT_READY": 409,
    "ERR_COLD_CHAIN_EXCURSION": 409,
    "ERR_READING_OUT_OF_ORDER": 422,
    "ERR_INVALID_STAGING_WINDOW": 422,
    "ERR_SHIP_DATE_OUTSIDE_DELIVERY_WINDOW": 422,
    "ERR_INSUFFICIENT_PROPAGATION_LEAD_TIME": 422,
    "ERR_PROPAGATION_SLOT_CONFLICT": 409,
    "ERR_CONTRACT_WINDOW_OVERLAP": 409,
    "ERR_ZONE_CAPACITY_EXCEEDED": 409,
    # --- uniqueness ---------------------------------------------------------
    "ERR_DUPLICATE_CROP_YEAR": 409,
    "ERR_DUPLICATE_LOT_CODE": 409,
    "ERR_DUPLICATE_BREWERY_LICENSE": 409,
    "ERR_DUPLICATE_RESOURCE_CODE": 409,
    # --- business rules -----------------------------------------------------
    "ERR_ORDER_HAS_NO_LINES": 422,
    "ERR_BELOW_MINIMUM_ORDER_QUANTITY": 422,
    "ERR_INVALID_CARRY_FORWARD_TARGET": 422,
    "ERR_CARRY_FORWARD_EXCEEDS_CAP": 422,
    "ERR_NO_UNCOMMITTED_VOLUME": 422,
    "ERR_NO_SUBSTITUTE_AVAILABLE": 422,
    "ERR_RESALE_EXCEEDS_DEFAULTED_VOLUME": 422,
    "ERR_RESALE_BUYER_INVALID": 422,
    "ERR_CONTRACT_VOLUME_EXHAUSTED": 422,
    "ERR_MALT_LOT_INSUFFICIENT_QUANTITY": 422,
    "ERR_SPOT_INVENTORY_INSUFFICIENT": 422,
    # --- fiscal -------------------------------------------------------------
    "ERR_BREWER_CREDIT_HOLD": 402,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_ORDER_CREDIT_NOT_APPROVED": 402,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
}


class ApiError(Exception):
    """Any refusal the API reports through the error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").lower().capitalize()


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)
