"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status (PRD §2.2 error envelope)."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for every error_id in the PRD §5 catalogue.
ERROR_HTTP = {
    # Auth
    "ERR_MISSING_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    # Validation
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_SCAC": 409,
    "ERR_MODE_MISMATCH": 422,
    "ERR_RATE_WINDOW_OVERLAP": 409,
    "ERR_UNKNOWN_ACCESSORIAL": 422,
    # Not found
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_RATE_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_TENDER_NOT_FOUND": 404,
    "ERR_LOAD_NOT_FOUND": 404,
    "ERR_APPT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    # State (Carrier / Rate)
    "ERR_CARRIER_NOT_ACTIVE": 409,
    "ERR_CARRIER_NOT_SUSPENDED": 409,
    "ERR_RATE_NOT_ACTIVE": 409,
    # State (Order)
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    # State (Shipment)
    "ERR_SHIPMENT_NOT_PENDING": 409,
    "ERR_SHIPMENT_ALREADY_TENDERED": 409,
    "ERR_SHIPMENT_NOT_TENDERED": 409,
    "ERR_SHIPMENT_NOT_BOOKED": 409,
    "ERR_SHIPMENT_NOT_IN_TRANSIT": 409,
    "ERR_SHIPMENT_NOT_CANCELLABLE": 409,
    "ERR_SHIPMENT_NOT_DELIVERED": 409,
    "ERR_NO_ELIGIBLE_CARRIER": 409,
    # State (Tender)
    "ERR_TENDER_NOT_OFFERED": 409,
    # State (Load)
    "ERR_LOAD_NOT_BUILDING": 409,
    "ERR_LOAD_NOT_DISPATCHED": 409,
    "ERR_EMPTY_LOAD": 409,
    "ERR_NO_DOCK_APPOINTMENT": 409,
    "ERR_LOAD_HAS_UNDELIVERED_SHIPMENTS": 409,
    "ERR_LOAD_CAPACITY_EXCEEDED": 409,
    "ERR_SHIPMENT_NOT_ON_BUILDING_LOAD": 409,
    # Concurrency
    "ERR_STALE_LOAD_VERSION": 412,
    # State (DockAppointment)
    "ERR_APPT_NOT_SCHEDULED": 409,
    "ERR_APPT_NOT_CHECKED_IN": 409,
    "ERR_DOCK_DOUBLE_BOOKED": 409,
    # State (FreightInvoice)
    "ERR_INVOICE_NOT_RECEIVED": 409,
    "ERR_INVOICE_NOT_AUDITED": 409,
    "ERR_VARIANCE_EXCEEDS_TOLERANCE": 409,
    # State (Claim)
    "ERR_CLAIM_NOT_OPEN": 409,
}


def err(error_id, message=None):
    """Build an ApiError for a known error_id, looking up the HTTP status."""
    return ApiError(error_id, ERROR_HTTP[error_id], message)
