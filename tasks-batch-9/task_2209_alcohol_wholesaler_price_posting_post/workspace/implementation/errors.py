"""Error catalogue and the ApiError exception (PRD sections 2.2 / 5)."""


class ApiError(Exception):
    """An error that is rendered through the standard error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# ---------------------------------------------------------------------------
# Error id -> HTTP status, exactly as PRD section 5 lists them.
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STATE_PROGRAM_NOT_FOUND": 404,
    "ERR_WHOLESALER_NOT_FOUND": 404,
    "ERR_LICENSEE_USER_NOT_FOUND": 404,
    "ERR_BRAND_NOT_FOUND": 404,
    "ERR_PRICE_SCHEDULE_NOT_FOUND": 404,
    "ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND": 404,
    "ERR_QUANTITY_DISCOUNT_TIER_NOT_FOUND": 404,
    "ERR_COMBINATION_SALE_NOT_FOUND": 404,
    "ERR_HOLD_AMENDMENT_NOT_FOUND": 404,
    "ERR_ERROR_CORRECTION_NOT_FOUND": 404,
    "ERR_RETAILER_INVOICE_NOT_FOUND": 404,
    "ERR_INVOICE_LINE_NOT_FOUND": 404,
    "ERR_COMPLIANCE_AUDIT_NOT_FOUND": 404,
    "ERR_AUDIT_FINDING_NOT_FOUND": 404,
    "ERR_FORBIDDEN_WHOLESALER_SCOPE": 403,
    "ERR_STALE_SCHEDULE_VERSION": 412,
    "ERR_STALE_WHOLESALER_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_LICENSE_NOT_ACTIVE": 409,
    "ERR_BRAND_NOT_REGISTERED": 409,
    "ERR_BRAND_REGISTRATION_OVERLAP": 409,
    "ERR_SELF_REFERENCE_NOT_ALLOWED": 409,
    "ERR_HOLD_WINDOW_CLOSED": 409,
    "ERR_HOLD_WINDOW_OVERRUNS_EFFECTIVE": 409,
    "ERR_COMBINATION_COOLDOWN_VIOLATION": 409,
    "ERR_DUPLICATE_SCHEDULE_ITEM": 409,
    "ERR_DUPLICATE_POSTING_MONTH": 409,
    "ERR_DUPLICATE_AUDIT_PERIOD": 409,
    "ERR_QUANTITY_DISCOUNT_PROHIBITED": 422,
    "ERR_COMBINATION_SALE_PROHIBITED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_AMENDMENT_NOT_A_REDUCTION": 422,
    "ERR_AMENDMENT_BELOW_REFERENCE": 422,
    "ERR_CASE_PRICE_EXCEEDS_UNIT_AGGREGATE": 422,
    "ERR_COMBINATION_BELOW_FLOOR": 422,
    "ERR_DISCOUNT_EXCEEDS_STATE_CAP": 422,
    "ERR_CORRECTION_EXCEEDS_CLERICAL_LIMIT": 422,
    "ERR_CORRECTION_LIMIT_EXCEEDED": 409,
    "ERR_CORRECTION_WINDOW_CLOSED": 409,
    "ERR_SCHEDULE_HAS_NO_ITEMS": 422,
    "ERR_ZERO_QUANTITY_LINE": 422,
    "ERR_COMBINATION_TOO_FEW_MEMBERS": 422,
    "ERR_ITEM_NOT_ON_SAME_SCHEDULE": 422,
    "ERR_NO_FLAGGED_INVOICES": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or name an unknown role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this operation.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_STATE_PROGRAM_NOT_FOUND": "The referenced state program does not exist.",
    "ERR_WHOLESALER_NOT_FOUND": "The referenced wholesaler does not exist.",
    "ERR_LICENSEE_USER_NOT_FOUND": "The referenced licensee user does not exist.",
    "ERR_BRAND_NOT_FOUND": "The referenced brand does not exist.",
    "ERR_PRICE_SCHEDULE_NOT_FOUND": "The referenced price schedule does not exist.",
    "ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND": "The referenced price schedule item does not exist.",
    "ERR_QUANTITY_DISCOUNT_TIER_NOT_FOUND": "The referenced quantity discount tier does not exist.",
    "ERR_COMBINATION_SALE_NOT_FOUND": "The referenced combination sale does not exist.",
    "ERR_HOLD_AMENDMENT_NOT_FOUND": "The referenced hold amendment does not exist.",
    "ERR_ERROR_CORRECTION_NOT_FOUND": "The referenced error correction does not exist.",
    "ERR_RETAILER_INVOICE_NOT_FOUND": "The referenced retailer invoice does not exist.",
    "ERR_INVOICE_LINE_NOT_FOUND": "The referenced invoice line does not exist.",
    "ERR_COMPLIANCE_AUDIT_NOT_FOUND": "The referenced compliance audit does not exist.",
    "ERR_AUDIT_FINDING_NOT_FOUND": "The referenced audit finding does not exist.",
    "ERR_FORBIDDEN_WHOLESALER_SCOPE": "The target resource belongs to a different wholesaler.",
    "ERR_STALE_SCHEDULE_VERSION": "The supplied expected schedule version is stale.",
    "ERR_STALE_WHOLESALER_VERSION": "The supplied expected wholesaler version is stale.",
    "ERR_INVALID_STATE": "The target entity is not in a state that admits this operation.",
    "ERR_LICENSE_NOT_ACTIVE": "The governing wholesaler licence is not ACTIVE.",
    "ERR_BRAND_NOT_REGISTERED": "A brand behind an item of this schedule is not registered for the effective date.",
    "ERR_BRAND_REGISTRATION_OVERLAP": "The requested brand registration interval overlaps an existing registration.",
    "ERR_SELF_REFERENCE_NOT_ALLOWED": "A hold amendment may not reference an item of the same wholesaler.",
    "ERR_HOLD_WINDOW_CLOSED": "The post-and-hold window is not open.",
    "ERR_HOLD_WINDOW_OVERRUNS_EFFECTIVE": "The post-and-hold window would not end before the effective date.",
    "ERR_COMBINATION_COOLDOWN_VIOLATION": "The combination sale window violates the program cooldown buffer.",
    "ERR_DUPLICATE_SCHEDULE_ITEM": "The schedule already carries this brand, size and package.",
    "ERR_DUPLICATE_POSTING_MONTH": "The wholesaler already holds a live schedule for this posting month.",
    "ERR_DUPLICATE_AUDIT_PERIOD": "The wholesaler already holds a live audit for this period month.",
    "ERR_QUANTITY_DISCOUNT_PROHIBITED": "The state program does not permit quantity discount tiers.",
    "ERR_COMBINATION_SALE_PROHIBITED": "The state program does not permit combination sales.",
    "ERR_SEGREGATION_OF_DUTIES": "The certifying user may not be the user who filed the schedule.",
    "ERR_AMENDMENT_NOT_A_REDUCTION": "The amended case price is not a reduction.",
    "ERR_AMENDMENT_BELOW_REFERENCE": "The amended case price falls below the reference item's case price.",
    "ERR_CASE_PRICE_EXCEEDS_UNIT_AGGREGATE": "The case price exceeds the aggregate of its bottle prices.",
    "ERR_COMBINATION_BELOW_FLOOR": "The combined case price is below the minimum allowed price.",
    "ERR_DISCOUNT_EXCEEDS_STATE_CAP": "The discount percentage exceeds the state cap.",
    "ERR_CORRECTION_EXCEEDS_CLERICAL_LIMIT": "The correction variance exceeds the clerical limit.",
    "ERR_CORRECTION_LIMIT_EXCEEDED": "The schedule has reached its approved correction limit.",
    "ERR_CORRECTION_WINDOW_CLOSED": "The correction window has closed.",
    "ERR_SCHEDULE_HAS_NO_ITEMS": "The schedule carries no price schedule items.",
    "ERR_ZERO_QUANTITY_LINE": "The invoice line has a zero total quantity.",
    "ERR_COMBINATION_TOO_FEW_MEMBERS": "A combination sale needs at least two distinct member items.",
    "ERR_ITEM_NOT_ON_SAME_SCHEDULE": "A member item does not belong to the declared schedule.",
    "ERR_NO_FLAGGED_INVOICES": "No flagged invoice of the wholesaler falls inside the audit period month.",
}


def err(error_id, message=None):
    """Build an ApiError from the catalogue."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)


def raise_err(error_id, message=None):
    raise err(error_id, message)
