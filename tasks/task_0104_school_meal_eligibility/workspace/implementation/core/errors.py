"""Error catalog and APIError exception. Per PRD §5."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog from SCAFFOLD §1.6 / PRD §5
ERRORS = {
    "ERR_VALIDATION": 422,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALLERGEN_BLOCK": 409,
    "ERR_DOCTOR_NOTE_REQUIRED": 422,
    "ERR_DUPLICATE_ALLERGEN": 409,
    "ERR_MEAL_ALREADY_SERVED_TODAY": 409,
    "ERR_PREPAID_BALANCE_INSUFFICIENT": 409,
    "ERR_CLAIM_PERIOD_OVERLAP": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_RENEWAL_INELIGIBLE": 422,
    "ERR_REFUND_MISMATCH": 422,
    "ERR_PARENT_EMAIL_TAKEN": 409,
    "ERR_MENU_ITEM_IN_USE": 409,
    "ERR_VERSION_MISMATCH": 412,
}


def raise_error(error_id: str, message: str = ""):
    http = ERRORS.get(error_id, 500)
    raise APIError(error_id, message or error_id, http)
