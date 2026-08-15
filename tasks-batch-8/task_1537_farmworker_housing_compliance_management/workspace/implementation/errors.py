"""Error catalog: error_id -> (http_status, default message)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _MESSAGES.get(error_id, error_id)


_MESSAGES = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": "X-User-ID or X-User-Role header missing or role not a declared role",
    "ERR_INSUFFICIENT_PERMISSIONS": "Role not permitted for this endpoint/transition, or Resident acting on another household's tenancy",
    "ERR_INVALID_REQUEST": "Missing required field, type mismatch, invalid enum value, or violated conditional field rule",
    "ERR_NOT_FOUND": "Referenced resource does not exist",
    "ERR_SITE_NOT_FOUND": "HousingSite id does not exist",
    "ERR_UNIT_NOT_FOUND": "HousingUnit id does not exist",
    "ERR_HOUSEHOLD_NOT_FOUND": "Household id does not exist",
    "ERR_TENANCY_NOT_FOUND": "Tenancy id does not exist",
    "ERR_WORK_ORDER_NOT_FOUND": "WorkOrder id does not exist",
    "ERR_INSPECTION_NOT_FOUND": "RegulatoryInspection id does not exist",
    "ERR_STALE_VERSION": "expected version does not match the parent's current version",
    "ERR_INVALID_STATE": "Requested status is not a declared transition from the entity's current status",
    "ERR_NO_COVERING_SEASON_WINDOW": "No PLANNED season window covers the current clock date for a site opening",
    "ERR_NO_CERTIFIED_UNIT": "Site cannot open operations without at least one CERTIFIED unit",
    "ERR_SITE_NOT_OPEN": "Operation requires the site status to be OPEN",
    "ERR_SITE_RESTRICTED": "Site compliance_posture is RESTRICTED; activations and notice rescissions blocked",
    "ERR_UNIT_CONDEMNED": "Unit is CONDEMNED (or notice_reason is CONDEMNATION); activation/rescission forbidden",
    "ERR_UNIT_UNDER_PEST_EXCLUSION": "move_in_date falls inside an APPLIED treatment's closed exclusion window",
    "ERR_REENTRY_BUFFER_ACTIVE": "Pest treatment cannot be CLEARED before clock_date > exclusion_end_date",
    "ERR_NO_VALID_CERTIFICATION": "Unit holds no PASSED certification with expiry_date >= clock_date",
    "ERR_OCCUPANCY_LIMIT_EXCEEDED": "Projected occupancy would exceed unit.max_occupancy",
    "ERR_SEASON_WINDOW_OVERLAP": "New window's closed interval intersects an existing window",
    "ERR_SEASON_GAP_TOO_SHORT": "Gap between non-overlapping windows is <= 14 days",
    "ERR_SEASON_PEST_TREATMENT_MISSING": "Season closure blocked: a live unit lacks an APPLIED/CLEARED treatment within the ACTIVE window dates",
    "ERR_HOUSEHOLD_NOT_ELIGIBLE": "Household eligibility_status is not ELIGIBLE",
    "ERR_MEMBER_ALREADY_HOUSED": "A household member belongs to another tenancy in ACTIVE or NOTICE",
    "ERR_EDUCATION_REFERRAL_REQUIRES_MINOR": "EDUCATION referral requires household minor_count >= 1",
    "ERR_AG_WORK_NOT_VERIFIED": "ELIGIBLE verification requires ag_work_verified = true",
    "ERR_WORK_ORDER_NOT_VERIFIED": "DAMAGE charge requires the source work order in VERIFIED or CLOSED",
    "ERR_LINKED_WORK_ORDERS_OPEN": "Complaint resolution blocked by non-terminal linked work orders",
    "ERR_UNRESOLVED_CRITICAL_FINDINGS": "Cure certification blocked: open_critical_count > 0",
    "ERR_ACTIVE_TENANCIES_REMAIN": "Closure/decommission blocked by tenancies in PENDING_MOVE_IN, ACTIVE, or NOTICE",
    "ERR_OPEN_WORK_ORDERS_REMAIN": "Closure/re-inspection blocked by non-terminal work orders",
    "ERR_NO_ACTIVE_DEDUCTION_AUTHORIZATION": "Payment requires an ACTIVE DeductionAuthorization on the household",
    "ERR_NOTHING_TO_COLLECT": "Capped deduction computes to <= 0 cents",
    "ERR_ENTRY_ALREADY_VOIDED": "Void target is not POSTED",
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": "Verifier/certifier X-User-ID equals the completer/issuer X-User-ID",
}

HTTP_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_HOUSEHOLD_NOT_FOUND": 404,
    "ERR_TENANCY_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_NO_COVERING_SEASON_WINDOW": 409,
    "ERR_NO_CERTIFIED_UNIT": 409,
    "ERR_SITE_NOT_OPEN": 409,
    "ERR_SITE_RESTRICTED": 409,
    "ERR_UNIT_CONDEMNED": 409,
    "ERR_UNIT_UNDER_PEST_EXCLUSION": 409,
    "ERR_REENTRY_BUFFER_ACTIVE": 409,
    "ERR_NO_VALID_CERTIFICATION": 409,
    "ERR_OCCUPANCY_LIMIT_EXCEEDED": 422,
    "ERR_SEASON_WINDOW_OVERLAP": 409,
    "ERR_SEASON_GAP_TOO_SHORT": 409,
    "ERR_SEASON_PEST_TREATMENT_MISSING": 409,
    "ERR_HOUSEHOLD_NOT_ELIGIBLE": 409,
    "ERR_MEMBER_ALREADY_HOUSED": 409,
    "ERR_EDUCATION_REFERRAL_REQUIRES_MINOR": 422,
    "ERR_AG_WORK_NOT_VERIFIED": 422,
    "ERR_WORK_ORDER_NOT_VERIFIED": 409,
    "ERR_LINKED_WORK_ORDERS_OPEN": 409,
    "ERR_UNRESOLVED_CRITICAL_FINDINGS": 409,
    "ERR_ACTIVE_TENANCIES_REMAIN": 409,
    "ERR_OPEN_WORK_ORDERS_REMAIN": 409,
    "ERR_NO_ACTIVE_DEDUCTION_AUTHORIZATION": 409,
    "ERR_NOTHING_TO_COLLECT": 422,
    "ERR_ENTRY_ALREADY_VOIDED": 409,
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": 403,
}


def err(error_id, message=None):
    return ApiError(error_id, HTTP_STATUS[error_id], message)
