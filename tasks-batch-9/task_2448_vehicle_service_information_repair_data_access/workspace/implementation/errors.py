"""Error catalogue -- PRD section 5 (Error Code Catalogue)."""


# error_id -> HTTP status code, verbatim from PRD section 5.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CROSS_SHOP_ACCESS": 403,
    "ERR_NOT_SEAT_HOLDER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_MANUFACTURER_NOT_FOUND": 404,
    "ERR_SHOP_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_ENTITLEMENT_NOT_FOUND": 404,
    "ERR_SEAT_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_PUBLICATION_NOT_FOUND": 404,
    "ERR_PUBLICATION_VERSION_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_JOB_NOT_FOUND": 404,
    "ERR_REFERENCED_RESOURCE_NOT_FOUND": 404,
    "ERR_STALE_ENTITLEMENT_VERSION": 412,
    "ERR_STALE_PUBLICATION_PARENT_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_JOB_REVALIDATION_REQUIRED": 409,
    "ERR_PARITY_NON_COMPLIANT": 409,
    "ERR_LICENSE_NOT_ACTIVE": 409,
    "ERR_ENTITLEMENT_NOT_ACTIVE": 409,
    "ERR_TECHNICIAN_NOT_VERIFIED": 409,
    "ERR_VERSION_NOT_PUBLISHED": 409,
    "ERR_SECURITY_CREDENTIAL_EXPIRED": 409,
    "ERR_TOOL_ATTESTATION_EXPIRED": 409,
    "ERR_CALIBRATION_DOC_REQUIRED": 422,
    "ERR_STALE_PUBLICATION_VERSION": 409,
    "ERR_TOOL_SHOP_MISMATCH": 422,
    "ERR_SEAT_CAP_EXCEEDED": 422,
    "ERR_NO_SEATS_AVAILABLE": 409,
    "ERR_ENTITLEMENT_WINDOW_CONFLICT": 409,
    "ERR_TOOL_WINDOW_CONFLICT": 409,
    "ERR_SESSION_WINDOW_OUTSIDE_ENTITLEMENT": 422,
    "ERR_INSUFFICIENT_DATA_CREDIT": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of the five declared roles.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_CROSS_SHOP_ACCESS": "A ShopManager may only address its own shop.",
    "ERR_NOT_SEAT_HOLDER": "A Technician may only act through a seat assigned to itself.",
    "ERR_SEGREGATION_OF_DUTIES": "The publisher of a version may not be the operator that validated it.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_MANUFACTURER_NOT_FOUND": "Manufacturer not found.",
    "ERR_SHOP_NOT_FOUND": "Shop not found.",
    "ERR_LICENSE_NOT_FOUND": "License not found.",
    "ERR_TECHNICIAN_NOT_FOUND": "Technician not found.",
    "ERR_ENTITLEMENT_NOT_FOUND": "Shop entitlement not found.",
    "ERR_SEAT_ASSIGNMENT_NOT_FOUND": "Seat assignment not found.",
    "ERR_PUBLICATION_NOT_FOUND": "Publication not found.",
    "ERR_PUBLICATION_VERSION_NOT_FOUND": "Publication version not found.",
    "ERR_SESSION_NOT_FOUND": "Gateway session not found.",
    "ERR_JOB_NOT_FOUND": "Module programming job not found.",
    "ERR_REFERENCED_RESOURCE_NOT_FOUND": "A secondary reference does not resolve.",
    "ERR_STALE_ENTITLEMENT_VERSION": "expected_entitlement_version does not match the entitlement's current version.",
    "ERR_STALE_PUBLICATION_PARENT_VERSION": "expected_publication_version does not match the publication's current version.",
    "ERR_INVALID_STATE": "The requested transition is not declared from the row's current state.",
    "ERR_JOB_REVALIDATION_REQUIRED": "The job must be re-pinned before it can complete.",
    "ERR_PARITY_NON_COMPLIANT": "The granting manufacturer's pricing parity verdict is NON_COMPLIANT.",
    "ERR_LICENSE_NOT_ACTIVE": "The license is not ACTIVE.",
    "ERR_ENTITLEMENT_NOT_ACTIVE": "The entitlement behind the seat is not ACTIVE.",
    "ERR_TECHNICIAN_NOT_VERIFIED": "The seated technician's identity is not VERIFIED.",
    "ERR_VERSION_NOT_PUBLISHED": "The publication version is not PUBLISHED.",
    "ERR_SECURITY_CREDENTIAL_EXPIRED": "The secure-gateway credential has lapsed.",
    "ERR_TOOL_ATTESTATION_EXPIRED": "The diagnostic tool's OEM attestation has lapsed.",
    "ERR_CALIBRATION_DOC_REQUIRED": "A VALIDATED and PUBLISHED CALIBRATION_DOC version is required for this cell.",
    "ERR_STALE_PUBLICATION_VERSION": "The pinned publication version is SUPERSEDED or RECALLED.",
    "ERR_TOOL_SHOP_MISMATCH": "The diagnostic tool belongs to a different shop.",
    "ERR_SEAT_CAP_EXCEEDED": "The requested commercial terms breach the license's constraints.",
    "ERR_NO_SEATS_AVAILABLE": "The entitlement has no seat available.",
    "ERR_ENTITLEMENT_WINDOW_CONFLICT": "The coverage window conflicts with a sibling entitlement window.",
    "ERR_TOOL_WINDOW_CONFLICT": "The occupation window overlaps an ACTIVE session on the same tool.",
    "ERR_SESSION_WINDOW_OUTSIDE_ENTITLEMENT": "The session window does not sit inside the entitlement window.",
    "ERR_INSUFFICIENT_DATA_CREDIT": "The shop's data credit balance is below the provisional charge.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


def err(error_id, message=None):
    """Build an ApiError ready to be raised."""
    return ApiError(error_id, message)
