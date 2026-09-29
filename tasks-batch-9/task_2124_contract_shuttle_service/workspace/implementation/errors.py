"""Error catalogue (PRD section 5 / SCAFFOLD section 1.6).

Every error_id in the catalogue is bound to its HTTP status here, so a raise
site only has to name the error.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    # --- authentication / authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_DRIVER_NOT_ASSIGNED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # --- existence ---
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_DRIVER_NOT_FOUND": 404,
    "ERR_TRIP_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_MAINTENANCE_ORDER_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_MEMO_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    # --- optimistic concurrency ---
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_STALE_ROUTE_VERSION": 412,
    # --- state preconditions ---
    "ERR_CONTRACT_NOT_DRAFT": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_ROUTE_NOT_DRAFT": 409,
    "ERR_ROUTE_NOT_PUBLISHED": 409,
    "ERR_TRIP_NOT_SCHEDULABLE": 409,
    "ERR_TRIP_NOT_ASSIGNED": 409,
    "ERR_TRIP_NOT_IN_SERVICE": 409,
    "ERR_REQUEST_NOT_PENDING": 409,
    "ERR_REQUEST_NOT_MATCHED": 409,
    "ERR_REPORT_NOT_SUBMITTABLE": 409,
    "ERR_REPORT_NOT_SUBMITTED": 409,
    "ERR_MEMO_NOT_ISSUED": 409,
    "ERR_OFFER_NOT_OPEN": 409,
    "ERR_OFFER_NOT_COUNTERED": 409,
    "ERR_MAINTENANCE_ORDER_NOT_OPEN": 409,
    "ERR_VEHICLE_UNAVAILABLE": 409,
    # --- safety / compliance ---
    "ERR_VEHICLE_IN_MAINTENANCE_WINDOW": 422,
    "ERR_DRIVER_NOT_ADA_CERTIFIED": 422,
    "ERR_ADA_VEHICLE_REQUIRED": 422,
    "ERR_ADA_FLEET_SHORTFALL": 422,
    # --- scheduling constraints ---
    "ERR_FLEET_CODE_DUPLICATE": 409,
    "ERR_VEHICLE_BLOCK_CONFLICT": 409,
    "ERR_DRIVER_BLOCK_CONFLICT": 409,
    "ERR_DRIVER_DUTY_EXCEEDED": 422,
    "ERR_TRIP_SEATS_EXHAUSTED": 409,
    # --- temporal ---
    "ERR_DATE_OUT_OF_TERM": 422,
    "ERR_PERIOD_OUT_OF_TERM": 422,
    "ERR_PERIOD_OVERLAP": 409,
    "ERR_NO_ELIGIBLE_ROUTE": 422,
    "ERR_RENEWAL_WINDOW_CLOSED": 422,
    "ERR_TRIP_DEPARTURE_TOO_EARLY": 422,
    # --- referential / fiscal ---
    "ERR_VEHICLE_BRANDING_MISMATCH": 422,
    "ERR_TRIP_CONTRACT_MISMATCH": 422,
    "ERR_MEMO_AMOUNT_EXCEEDS_CAP": 422,
    "ERR_COUNTER_RATE_OUT_OF_BOUNDS": 422,
    # --- fallback for undeclared routes ---
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, empty or name an unknown role.",
    "ERR_FORBIDDEN_ROLE": "The caller's role is not authorised for this endpoint.",
    "ERR_DRIVER_NOT_ASSIGNED": "The acting driver is not assigned to this trip.",
    "ERR_SEGREGATION_OF_DUTIES": "The approver may not be the submitter of the report.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in 1..100 and offset an integer >= 0.",
    "ERR_CONTRACT_NOT_FOUND": "No service contract with the given id.",
    "ERR_ROUTE_NOT_FOUND": "No route with the given id.",
    "ERR_VEHICLE_NOT_FOUND": "No vehicle with the given id.",
    "ERR_DRIVER_NOT_FOUND": "No driver with the given id.",
    "ERR_TRIP_NOT_FOUND": "No trip with the given id.",
    "ERR_REQUEST_NOT_FOUND": "No on-demand request with the given id.",
    "ERR_MAINTENANCE_ORDER_NOT_FOUND": "No maintenance order with the given id.",
    "ERR_REPORT_NOT_FOUND": "No service period report with the given id.",
    "ERR_MEMO_NOT_FOUND": "No credit memo with the given id.",
    "ERR_OFFER_NOT_FOUND": "No renewal offer with the given id.",
    "ERR_STALE_CONTRACT_VERSION": "expected_contract_version does not match the contract's current version.",
    "ERR_STALE_ROUTE_VERSION": "expected_route_version does not match the route's current version.",
}
