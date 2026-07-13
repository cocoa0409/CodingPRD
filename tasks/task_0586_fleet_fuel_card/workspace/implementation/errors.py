"""Error catalog (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_FLEET": 403,
    "ERR_VALIDATION": 400,
    "ERR_FLEET_ACCOUNT_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_DRIVER_NOT_FOUND": 404,
    "ERR_CARD_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_FAULT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_CARD_NOT_ACTIVE": 409,
    "ERR_INVALID_CARD_STATE": 409,
    "ERR_INVALID_TXN_STATE": 409,
    "ERR_INVALID_ALERT_STATE": 409,
    "ERR_INVALID_FAULT_STATE": 409,
    "ERR_INVALID_REPORT_STATE": 409,
    "ERR_VEHICLE_OUT_OF_SERVICE": 409,
    "ERR_NO_ACTIVE_ASSIGNMENT": 409,
    "ERR_PRODUCT_NOT_ALLOWED": 422,
    "ERR_OUTSIDE_ALLOWED_HOURS": 422,
    "ERR_GALLON_LIMIT_EXCEEDED": 422,
    "ERR_DRIVER_DOUBLE_BOOKED": 409,
    "ERR_MAINTENANCE_OVERLAP": 409,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_MISSING_MAINTENANCE_WINDOW": 422,
    "ERR_DAILY_LIMIT_EXCEEDED": 402,
    "ERR_CREDIT_EXCEEDED": 402,
    "ERR_PERIOD_NOT_SETTLED": 409,
    "ERR_STALE_CARD_VERSION": 412,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid X-User-ID / X-User-Role headers.",
    "ERR_UNAUTHORIZED": "Role is not permitted to invoke this operation.",
    "ERR_FORBIDDEN_FLEET": "FleetManager may only act on resources of its own fleet account.",
    "ERR_VALIDATION": "Request body or query parameters are invalid.",
    "ERR_FLEET_ACCOUNT_NOT_FOUND": "Fleet account does not exist.",
    "ERR_VEHICLE_NOT_FOUND": "Vehicle does not exist.",
    "ERR_DRIVER_NOT_FOUND": "Driver does not exist.",
    "ERR_CARD_NOT_FOUND": "Fuel card does not exist.",
    "ERR_ASSIGNMENT_NOT_FOUND": "Card assignment does not exist.",
    "ERR_TRANSACTION_NOT_FOUND": "Transaction does not exist.",
    "ERR_ALERT_NOT_FOUND": "Fraud alert does not exist.",
    "ERR_FAULT_NOT_FOUND": "Telematics fault does not exist.",
    "ERR_REPORT_NOT_FOUND": "IFTA report does not exist.",
    "ERR_CARD_NOT_ACTIVE": "Card is not ACTIVE.",
    "ERR_INVALID_CARD_STATE": "Card is not in a state that permits this transition.",
    "ERR_INVALID_TXN_STATE": "Transaction posting_status does not permit this transition.",
    "ERR_INVALID_ALERT_STATE": "Fraud alert is not in a state that permits this transition.",
    "ERR_INVALID_FAULT_STATE": "Telematics fault is not in a state that permits this transition.",
    "ERR_INVALID_REPORT_STATE": "IFTA report is not in a state that permits this transition.",
    "ERR_VEHICLE_OUT_OF_SERVICE": "Vehicle is not in service.",
    "ERR_NO_ACTIVE_ASSIGNMENT": "No ACTIVE card assignment covers the purchase instant.",
    "ERR_PRODUCT_NOT_ALLOWED": "Product is not in the card's allowed_products.",
    "ERR_OUTSIDE_ALLOWED_HOURS": "Purchase time is outside the card's permitted hour window.",
    "ERR_GALLON_LIMIT_EXCEEDED": "Gallons exceed the card's per_txn_gallon_limit.",
    "ERR_DRIVER_DOUBLE_BOOKED": "Assignment interval overlaps another ACTIVE assignment of the same driver.",
    "ERR_MAINTENANCE_OVERLAP": "Buffered maintenance window collides with another non-CLEARED fault window.",
    "ERR_INVALID_INTERVAL": "Interval is not well-formed.",
    "ERR_MISSING_MAINTENANCE_WINDOW": "CRITICAL fault requires both maintenance window bounds.",
    "ERR_DAILY_LIMIT_EXCEEDED": "Card daily spend limit exceeded.",
    "ERR_CREDIT_EXCEEDED": "Account available credit exceeded.",
    "ERR_PERIOD_NOT_SETTLED": "Some in-period transactions are not SETTLED.",
    "ERR_STALE_CARD_VERSION": "expected_card_version does not match the card's current version.",
}


def err(error_id, message=None):
    return ApiError(error_id, CATALOG[error_id], message)
