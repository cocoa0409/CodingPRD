"""Custom exception class and error metadata."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Error catalog: error_id -> (http_status, default message)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers missing."),
    "ERR_FORBIDDEN": (403, "Role not permitted for this operation."),
    "ERR_NOT_FOUND": (404, "Resource not found."),
    "ERR_INVALID_STATE": (409, "Resource is in a state that does not permit this transition."),
    "ERR_VERSION_MISMATCH": (409, "Version does not match server's current version."),
    "ERR_OWNERSHIP_MISMATCH": (403, "Acting Owner is not the Property owner."),
    "ERR_DUPLICATE_ROLL_YEAR": (409, "Another Assessment for this roll year is already issued/under appeal/finalized."),
    "ERR_APPEAL_WINDOW_CLOSED": (409, "Appeal window has closed."),
    "ERR_HEARING_INTERVAL_INVALID": (422, "Hearing interval is invalid."),
    "ERR_ROOM_DOUBLE_BOOKED": (409, "Hearing room is already booked for an overlapping interval."),
    "ERR_OFFICER_BUFFER_VIOLATED": (409, "Officer buffer constraint violated."),
    "ERR_BOE_OFFICER_CONFLICT": (403, "Officer cannot be the same user who issued the Assessment."),
    "ERR_OFFICER_MISMATCH": (403, "Acting officer is not the officer assigned at scheduling."),
    "ERR_DECISION_VALUE_INCONSISTENT": (422, "Decided value does not match decision outcome."),
    "ERR_EXEMPTION_DUPLICATE": (409, "Another APPROVED exemption already exists for this property/year/type."),
    "ERR_EXEMPTION_INELIGIBLE": (422, "Owner does not satisfy exemption eligibility."),
    "ERR_OVERPAYMENT": (409, "Payment amount is invalid or exceeds amount due."),
    "ERR_DUPLICATE_BILL": (409, "Another TaxBill exists for this property/roll year."),
    "ERR_ASSESSMENT_NOT_FINALIZED": (409, "Linked Assessment is not FINALIZED."),
    "ERR_EXEMPTIONS_PENDING": (409, "Pending exemption applications exist for this roll year."),
    "ERR_DEFERRAL_NOT_ELIGIBLE": (422, "Owner does not meet deferral eligibility criteria."),
    "ERR_VALIDATION_FAILED": (400, "Input validation failed."),
}


def raise_error(error_id: str, message: str = None):
    http_status, default_msg = ERROR_CATALOG[error_id]
    raise APIError(error_id, http_status, message or default_msg)
