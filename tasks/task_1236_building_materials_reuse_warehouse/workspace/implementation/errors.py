"""Error types and the full error catalog for the reuse warehouse API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)


# --- Auth ---
def err_unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden_role(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def err_not_owner(msg="Caller does not own the target resource"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, msg)


# --- Request shape ---
def err_invalid_request(msg="Malformed request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_time_window(msg="Window end must be strictly after window start"):
    return ApiError("ERR_INVALID_TIME_WINDOW", 400, msg)


# --- Not found ---
NOT_FOUND_IDS = {
    "donor": "ERR_DONOR_NOT_FOUND",
    "category": "ERR_CATEGORY_NOT_FOUND",
    "offer": "ERR_OFFER_NOT_FOUND",
    "job": "ERR_JOB_NOT_FOUND",
    "screening": "ERR_SCREENING_NOT_FOUND",
    "batch": "ERR_BATCH_NOT_FOUND",
    "item": "ERR_ITEM_NOT_FOUND",
    "zone": "ERR_ZONE_NOT_FOUND",
    "run": "ERR_RUN_NOT_FOUND",
    "account": "ERR_ACCOUNT_NOT_FOUND",
    "agreement": "ERR_AGREEMENT_NOT_FOUND",
    "sale": "ERR_SALE_NOT_FOUND",
    "line": "ERR_LINE_NOT_FOUND",
    "receipt": "ERR_RECEIPT_NOT_FOUND",
    "crew_member": "ERR_CREW_MEMBER_NOT_FOUND",
    "assignment": "ERR_ASSIGNMENT_NOT_FOUND",
    "vehicle": "ERR_VEHICLE_NOT_FOUND",
    "appointment": "ERR_APPOINTMENT_NOT_FOUND",
    "report": "ERR_REPORT_NOT_FOUND",
}


def err_not_found(resource, msg=None):
    return ApiError(
        NOT_FOUND_IDS[resource], 404, msg or ("%s does not exist" % resource)
    )
