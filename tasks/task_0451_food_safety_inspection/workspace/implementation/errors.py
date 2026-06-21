"""Error class and the full error catalog (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Default human-readable messages keyed by error id. http status is carried at
# raise time but we also keep a canonical map for sanity.
ERROR_HTTP = {
    # Auth
    "ERR_MISSING_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_ASSIGNED_INSPECTOR": 403,
    # Not found
    "ERR_ESTABLISHMENT_NOT_FOUND": 404,
    "ERR_PLAN_REVIEW_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_CODE_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_CLOSURE_ORDER_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    # Input
    "ERR_INVALID_REQUEST": 400,
    "ERR_MISSING_REJECTION_REASON": 400,
    "ERR_INVALID_RULING": 400,
    # OCC
    "ERR_STALE_INSPECTION_VERSION": 412,
    # Establishment
    "ERR_ESTABLISHMENT_NOT_PRELICENSE": 409,
    "ERR_ESTABLISHMENT_NOT_PERMITTED": 409,
    "ERR_ESTABLISHMENT_NOT_SUSPENDED": 409,
    "ERR_ESTABLISHMENT_NOT_REVOCABLE": 409,
    "ERR_ESTABLISHMENT_REVOKED": 409,
    # Plan review
    "ERR_PLAN_REVIEW_NOT_SUBMITTED": 409,
    "ERR_PLAN_REVIEW_NOT_REJECTED": 409,
    "ERR_PLAN_REVIEW_NOT_APPROVED": 409,
    # Inspection
    "ERR_INSPECTION_NOT_SCHEDULED": 409,
    "ERR_INSPECTION_NOT_IN_PROGRESS": 409,
    "ERR_INSPECTION_NOT_COMPLETED": 409,
    "ERR_INSPECTION_NOT_AMENDING": 409,
    "ERR_INSPECTION_NOT_EDITABLE": 409,
    "ERR_INVALID_REINSPECTION_TARGET": 409,
    "ERR_INSPECTOR_DOUBLE_BOOKED": 409,
    "ERR_CODE_RETIRED": 409,
    # Route
    "ERR_ROUTE_NOT_PLANNED": 409,
    "ERR_ROUTE_NOT_DISPATCHED": 409,
    "ERR_ROUTE_CAPACITY_EXCEEDED": 409,
    "ERR_ROUTE_DATE_IN_PAST": 409,
    # Closure
    "ERR_NO_ACTIVE_CLOSURE_ORDER": 409,
    "ERR_CLOSURE_ORDER_NOT_ACTIVE": 409,
    # Complaint
    "ERR_COMPLAINT_NOT_RECEIVED": 409,
    "ERR_COMPLAINT_NOT_TRIAGED": 409,
    "ERR_COMPLAINT_NOT_DISPATCHED": 409,
    "ERR_COMPLAINT_INSPECTION_OPEN": 409,
    # Enforcement
    "ERR_CASE_NOT_OPENED": 409,
    "ERR_CASE_NOT_SCHEDULED": 409,
    "ERR_CASE_NOT_HEARD": 409,
    "ERR_HEARING_IN_PAST": 409,
    "ERR_HEARING_NOT_REACHED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP.get(error_id, 400), message)
