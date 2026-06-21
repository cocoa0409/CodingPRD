"""Error catalogue. error_id -> http_status, plus the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_ASSIGNED_REVIEWER": 403,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_CORRECTION_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_SWO_NOT_FOUND": 404,
    "ERR_CO_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_LICENSE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_PERMIT_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_CONTRACTOR_UNVERIFIED": 409,
    "ERR_WORK_STOPPED": 409,
    "ERR_OPEN_CORRECTIONS": 409,
    "ERR_ROUGH_NOT_PASSED": 409,
    "ERR_OUTSIDE_SLOT_WINDOW": 409,
    "ERR_INSPECTOR_DOUBLE_BOOKED": 409,
    "ERR_SLOT_CAPACITY_FULL": 409,
    "ERR_BALANCE_DUE": 409,
    "ERR_NO_CERTIFICATE": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this operation.",
    "ERR_NOT_ASSIGNED_REVIEWER": "The acting reviewer is not assigned to this review.",
    "ERR_PERMIT_NOT_FOUND": "Permit not found.",
    "ERR_CONTRACTOR_NOT_FOUND": "Contractor not found.",
    "ERR_JURISDICTION_NOT_FOUND": "Jurisdiction not found.",
    "ERR_REVIEW_NOT_FOUND": "Plan review not found.",
    "ERR_CORRECTION_NOT_FOUND": "Correction notice not found.",
    "ERR_INSPECTION_NOT_FOUND": "Inspection not found.",
    "ERR_SLOT_NOT_FOUND": "Inspection slot not found.",
    "ERR_SWO_NOT_FOUND": "Stop-work order not found.",
    "ERR_CO_NOT_FOUND": "Certificate of occupancy not found.",
    "ERR_INVALID_REQUEST": "The request body is missing required fields or has invalid values.",
    "ERR_DUPLICATE_LICENSE": "A unique identifier collides with an existing record.",
    "ERR_INVALID_STATE": "The resource is not in a valid state for this transition.",
    "ERR_STALE_PERMIT_VERSION": "The expected permit version does not match the current version.",
    "ERR_SEGREGATION_OF_DUTIES": "The plan approver may not perform the final inspection sign-off.",
    "ERR_CONTRACTOR_UNVERIFIED": "The contractor is not verified.",
    "ERR_WORK_STOPPED": "An active stop-work order blocks this operation.",
    "ERR_OPEN_CORRECTIONS": "Open corrections prevent this operation (or none exist where one is required).",
    "ERR_ROUGH_NOT_PASSED": "A passed ROUGH inspection is required first.",
    "ERR_OUTSIDE_SLOT_WINDOW": "The requested interval is not contained in the slot window.",
    "ERR_INSPECTOR_DOUBLE_BOOKED": "The inspector already has an overlapping inspection.",
    "ERR_SLOT_CAPACITY_FULL": "The slot has no remaining capacity.",
    "ERR_BALANCE_DUE": "The balance due must be zero.",
    "ERR_NO_CERTIFICATE": "An issued certificate of occupancy is required.",
}
