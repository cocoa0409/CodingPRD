"""Error catalog and the exception type routes raise to signal an API error."""

# error_id -> http_status, straight from SCAFFOLD.yaml Table 6 / PRD section 5
ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_HAZARD_PLAN_NOT_FOUND": 404,
    "ERR_POD_NOT_FOUND": 404,
    "ERR_STAFF_MEMBER_NOT_FOUND": 404,
    "ERR_SHIFT_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_COUNTERMEASURE_NOT_FOUND": 404,
    "ERR_INVENTORY_LOT_NOT_FOUND": 404,
    "ERR_ALLOCATION_REQUEST_NOT_FOUND": 404,
    "ERR_DISPENSING_EVENT_NOT_FOUND": 404,
    "ERR_DRILL_NOT_FOUND": 404,
    "ERR_SITUATION_REPORT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_CREDENTIAL_EXPIRED": 422,
    "ERR_CREDENTIAL_NOT_VERIFIED": 422,
    "ERR_INVALID_TIME_RANGE": 400,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_POD_CAPACITY_EXCEEDED": 409,
    "ERR_POD_NOT_OPERATIONAL": 409,
    "ERR_HAZARD_PLAN_NOT_ACTIVATED": 409,
    "ERR_SOURCE_ROLE_MISMATCH": 403,
    "ERR_INSUFFICIENT_INVENTORY": 409,
    "ERR_INVALID_SOURCE_CONFIGURATION": 400,
    "ERR_POD_NOT_READY_FOR_STAND_DOWN": 409,
    "ERR_POD_STAFF_ONSITE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_EXPIRATION": 400,
    "ERR_VALIDATION": 400,
}


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int = None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)


NOT_FOUND_ERROR_FOR_ENTITY = {
    "HazardPlan": "ERR_HAZARD_PLAN_NOT_FOUND",
    "POD": "ERR_POD_NOT_FOUND",
    "StaffMember": "ERR_STAFF_MEMBER_NOT_FOUND",
    "ShiftAssignment": "ERR_SHIFT_ASSIGNMENT_NOT_FOUND",
    "Countermeasure": "ERR_COUNTERMEASURE_NOT_FOUND",
    "InventoryLot": "ERR_INVENTORY_LOT_NOT_FOUND",
    "AllocationRequest": "ERR_ALLOCATION_REQUEST_NOT_FOUND",
    "DispensingEvent": "ERR_DISPENSING_EVENT_NOT_FOUND",
    "Drill": "ERR_DRILL_NOT_FOUND",
    "SituationReport": "ERR_SITUATION_REPORT_NOT_FOUND",
}
