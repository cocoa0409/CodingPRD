"""Error catalogue (PRD section 5) and the ApiError exception."""

HTTP_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_AIRLINE_SCOPE_VIOLATION": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_FLIGHT_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_CART_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_FLIGHT_VERSION": 412,
    "ERR_STALE_CART_VERSION": 412,
    # state
    "ERR_INVALID_FLIGHT_STATE": 409,
    "ERR_INVALID_BATCH_STATE": 409,
    "ERR_INVALID_CART_STATE": 409,
    "ERR_INVALID_RUN_STATE": 409,
    "ERR_INVALID_RESOURCE_STATE": 409,
    "ERR_FLIGHT_COUNTS_LOCKED": 409,
    "ERR_BATCH_NOT_RELEASED": 409,
    "ERR_MANIFEST_NOT_ISSUED": 409,
    # food safety
    "ERR_HACCP_STEP_MISSING": 422,
    "ERR_HACCP_HOLD_ACTIVE": 422,
    "ERR_HACCP_REWORK_LIMIT": 422,
    "ERR_RELEASE_DEADLINE_PASSED": 422,
    # compliance
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_BONDED_REUSE_FORBIDDEN": 422,
    "ERR_BONDED_WASTE_DISPOSAL_INVALID": 422,
    "ERR_AIRLINE_SUSPENDED": 422,
    # coherence
    "ERR_STORAGE_CLASS_MISMATCH": 422,
    "ERR_CART_FLIGHT_MISMATCH": 422,
    "ERR_SPEC_RETIRED": 422,
    "ERR_SPEC_AIRLINE_MISMATCH": 422,
    # capacity / uniqueness / conservation
    "ERR_CART_CAPACITY_EXCEEDED": 422,
    "ERR_STORE_CAPACITY_EXCEEDED": 422,
    "ERR_SEAL_NUMBER_DUPLICATE": 422,
    "ERR_DUPLICATE_SEAT_ORDER": 422,
    "ERR_PRODUCED_QTY_EXCEEDS_PLAN": 422,
    "ERR_UPLIFT_UNITS_MISMATCH": 422,
    "ERR_DISPOSITION_UNITS_MISMATCH": 422,
    # temporal / slotting
    "ERR_SPECIAL_MEAL_CUTOFF_PASSED": 422,
    "ERR_SLOT_WINDOW_INVALID": 422,
    "ERR_SLOT_OUTSIDE_FLIGHT_WINDOW": 422,
    "ERR_TRUCK_SLOT_CONFLICT": 422,
    "ERR_STAND_CAPACITY_CONFLICT": 422,
    "ERR_SLOT_RESOURCE_UNAVAILABLE": 422,
    # cost ceiling
    "ERR_COST_CAP_EXCEEDED": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Missing or unknown X-User-ID.",
    "ERR_FORBIDDEN_ROLE": "The acting role may not perform this operation.",
    "ERR_AIRLINE_SCOPE_VIOLATION": "The airline representative may only reach its own airline's rows.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_RESOURCE_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_FLIGHT_NOT_FOUND": "The referenced flight does not exist.",
    "ERR_BATCH_NOT_FOUND": "The referenced production batch does not exist.",
    "ERR_CART_NOT_FOUND": "The referenced cart does not exist.",
    "ERR_STALE_FLIGHT_VERSION": "expected_flight_version does not match the stored flight version.",
    "ERR_STALE_CART_VERSION": "expected_cart_version does not match the stored cart version.",
    "ERR_INVALID_FLIGHT_STATE": "The flight is not in a state that allows this operation.",
    "ERR_INVALID_BATCH_STATE": "The production batch is not in a state that allows this operation.",
    "ERR_INVALID_CART_STATE": "The cart is not in a state that allows this operation.",
    "ERR_INVALID_RUN_STATE": "The delivery run is not in a state that allows this operation.",
    "ERR_INVALID_RESOURCE_STATE": "The resource is not in a state that allows this operation.",
    "ERR_FLIGHT_COUNTS_LOCKED": "The flight's passenger counts are already locked.",
    "ERR_BATCH_NOT_RELEASED": "The production batch has not been released.",
    "ERR_MANIFEST_NOT_ISSUED": "The loading manifest is not issued.",
    "ERR_HACCP_STEP_MISSING": "A required HACCP step has no recorded check.",
    "ERR_HACCP_HOLD_ACTIVE": "The latest HACCP check for a required step failed.",
    "ERR_HACCP_REWORK_LIMIT": "The batch has exhausted its rework rounds.",
    "ERR_RELEASE_DEADLINE_PASSED": "The batch release deadline has passed.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not perform both halves of this control.",
    "ERR_BONDED_REUSE_FORBIDDEN": "Bonded waste may not be reused or donated.",
    "ERR_BONDED_WASTE_DISPOSAL_INVALID": "The disposal method is not allowed for this waste regime.",
    "ERR_AIRLINE_SUSPENDED": "The airline is suspended or the flight is on production hold.",
    "ERR_STORAGE_CLASS_MISMATCH": "The batch storage zone does not match the cart storage class.",
    "ERR_CART_FLIGHT_MISMATCH": "The batch and the cart belong to different flights.",
    "ERR_SPEC_RETIRED": "The meal specification is retired.",
    "ERR_SPEC_AIRLINE_MISMATCH": "The meal specification belongs to another airline or cabin.",
    "ERR_CART_CAPACITY_EXCEEDED": "The cart does not have room for the requested units.",
    "ERR_STORE_CAPACITY_EXCEEDED": "The requirement does not fit the flight's storage zones.",
    "ERR_SEAL_NUMBER_DUPLICATE": "The seal number is already in use.",
    "ERR_DUPLICATE_SEAT_ORDER": "The seat already has a live special meal order on this flight.",
    "ERR_PRODUCED_QTY_EXCEEDS_PLAN": "produced_qty exceeds planned_qty.",
    "ERR_UPLIFT_UNITS_MISMATCH": "consumed_units plus returned_units does not equal the uplifted units.",
    "ERR_DISPOSITION_UNITS_MISMATCH": "The disposition units do not equal the returned units.",
    "ERR_SPECIAL_MEAL_CUTOFF_PASSED": "The special meal cutoff for this flight has passed.",
    "ERR_SLOT_WINDOW_INVALID": "window_start_utc is not strictly before window_end_utc.",
    "ERR_SLOT_OUTSIDE_FLIGHT_WINDOW": "The slot falls outside the flight's delivery band.",
    "ERR_TRUCK_SLOT_CONFLICT": "The truck already has an overlapping slot.",
    "ERR_STAND_CAPACITY_CONFLICT": "The stand cannot hold another concurrent run.",
    "ERR_SLOT_RESOURCE_UNAVAILABLE": "The truck or stand is unavailable.",
    "ERR_COST_CAP_EXCEEDED": "The load would push cost per passenger above the airline's cap.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)
        self.http_status = HTTP_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
