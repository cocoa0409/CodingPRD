"""Error classes and HTTP status mapping for the pharma e-commerce API."""

from __future__ import annotations


class ApiError(Exception):
    """Standard API error with error_id, http_status, and message."""

    def __init__(self, error_id: str, message: str = "", http_status: int = 400):
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status
        super().__init__(self.message)


# Default HTTP status codes per error_id (PRD §5)
ERROR_HTTP_STATUS = {
    # Auth / context
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_INVALID_REQUEST": 400,
    # Existence
    "ERR_NOT_FOUND": 404,
    "ERR_PLATFORM_NOT_FOUND": 404,
    "ERR_DRUG_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_PHARMACIST_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_PRESCRIPTION_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_RULE_NOT_FOUND": 404,
    # Concurrency / version
    "ERR_VERSION_MISMATCH": 409,
    "ERR_IDEMPOTENCY_CONFLICT": 409,
    # Drug / catalog
    "ERR_NDC_INVALID_FORMAT": 400,
    "ERR_NDC_DUPLICATE": 409,
    "ERR_CONTROL_CATEGORY_REQUIRES_PRESCRIPTION": 400,
    "ERR_DRUG_NOT_PENDING_REVIEW": 409,
    "ERR_DRUG_NOT_ON_SHELF": 409,
    "ERR_DRUG_NOT_OFF_SHELF": 409,
    "ERR_DRUG_NOT_PRESCRIBABLE": 422,
    # Vendor
    "ERR_VENDOR_NOT_ACTIVE": 409,
    "ERR_VENDOR_NOT_IN_REVIEW": 409,
    "ERR_RENEWAL_DATE_NOT_FUTURE": 422,
    # Pharmacist
    "ERR_PHARMACIST_NOT_ACTIVE": 403,
    # Customer
    "ERR_REAL_NAME_REQUIRED": 403,
    # Prescription
    "ERR_PRESCRIPTION_NOT_IN_REVIEW": 409,
    "ERR_PRESCRIPTION_EXPIRED": 422,
    "ERR_PRESCRIBER_NOT_QUALIFIED": 422,
    "ERR_CONTRAINDICATION_VIOLATION": 422,
    "ERR_PRESCRIPTION_IN_USE": 409,
    "ERR_PRESCRIPTION_NOT_APPROVED": 409,
    # Purchase limits
    "ERR_PURCHASE_LIMIT_EXCEEDED": 422,
    "ERR_SPECIAL_POPULATION_RESTRICTED": 403,
    # Order
    "ERR_ORDER_NOT_REVIEWABLE": 409,
    "ERR_ORDER_NOT_PAYABLE": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_ORDER_NOT_APPROVED": 409,
    "ERR_ORDER_NOT_PAID": 409,
    "ERR_ORDER_NOT_DISPENSED": 409,
    "ERR_ORDER_NOT_SHIPPED": 409,
    "ERR_REVIEW_ALREADY_OPEN": 409,
    # Pharmacist review
    "ERR_REVIEW_NOT_IN_REVIEW": 409,
    "ERR_REVIEW_NOT_IN_REQUEST_CHANGE": 409,
    "ERR_REVIEWER_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": 403,
    "ERR_REVIEW_CHECKS_FAILED": 422,
    "ERR_REVIEW_NOTES_TOO_SHORT": 422,
    "ERR_REVIEW_MAX_REVISIONS": 409,
    # Cold chain
    "ERR_COLD_CHAIN_NOT_APPLICABLE": 422,
    "ERR_COURIER_NOT_QUALIFIED": 422,
    "ERR_COLD_CHAIN_SHIPMENT_REQUIRED": 409,
    "ERR_DISPOSAL_NOT_JUSTIFIED": 422,
    "ERR_COLD_CHAIN_OUT_OF_RANGE": 422,
    "ERR_SHIPMENT_NOT_DISPOSABLE": 409,
    # ADR
    "ERR_REPORT_NOT_REPORTED": 409,
    "ERR_REPORT_REQUIRES_FOLLOW_UP": 409,
    "ERR_REPORT_NOT_ARCHIVABLE": 409,
    "ERR_REPORTING_DEADLINE_PASSED": 422,
    "ERR_FOLLOW_UP_INCOMPLETE": 409,
}


def err(error_id: str, message: str = "") -> ApiError:
    """Construct an ApiError with the canonical HTTP status for the error_id."""
    return ApiError(error_id, message or error_id, ERROR_HTTP_STATUS.get(error_id, 400))
