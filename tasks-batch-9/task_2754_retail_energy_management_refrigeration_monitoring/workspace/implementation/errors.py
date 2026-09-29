"""Error catalog (PRD section 5) and the ApiError exception."""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "authentication required"),
    "ERR_UNAUTHORIZED": (403, "role not permitted for this operation"),
    "ERR_INVALID_REQUEST": (400, "request payload failed validation"),
    "ERR_STORE_NOT_FOUND": (404, "store not found"),
    "ERR_STANDARD_NOT_FOUND": (404, "setpoint standard not found"),
    "ERR_ACCOUNT_NOT_FOUND": (404, "utility account not found"),
    "ERR_BILL_NOT_FOUND": (404, "utility bill not found"),
    "ERR_DR_EVENT_NOT_FOUND": (404, "demand response event not found"),
    "ERR_CASE_NOT_FOUND": (404, "refrigeration case not found"),
    "ERR_EXCURSION_NOT_FOUND": (404, "temperature excursion not found"),
    "ERR_OVERRIDE_NOT_FOUND": (404, "lighting override not found"),
    "ERR_FAULT_NOT_FOUND": (404, "fault diagnostic not found"),
    "ERR_WORK_ORDER_NOT_FOUND": (404, "maintenance work order not found"),
    "ERR_RETROFIT_NOT_FOUND": (404, "retrofit project not found"),
    "ERR_STORE_SCOPE_VIOLATION": (403, "caller may only act on its own store"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "the same user may not perform both steps of this control"),
    "ERR_BMS_STATE_INVALID": (409, "building management system is not in a state that permits this action"),
    "ERR_STANDARD_STATE_INVALID": (409, "setpoint standard is not in a state that permits this action"),
    "ERR_BILL_STATE_INVALID": (409, "utility bill is not in a state that permits this action"),
    "ERR_DR_EVENT_STATE_INVALID": (409, "demand response event is not in a state that permits this action"),
    "ERR_SETTLEMENT_STATE_INVALID": (409, "settlement dimension is not in a state that permits this action"),
    "ERR_CASE_STATE_INVALID": (409, "refrigeration case is not in a state that permits this action"),
    "ERR_EXCURSION_STATE_INVALID": (409, "excursion is not in a state that permits this action"),
    "ERR_OVERRIDE_STATE_INVALID": (409, "lighting override is not in a state that permits revocation"),
    "ERR_FAULT_STATE_INVALID": (409, "fault diagnostic is not in a state that permits triage"),
    "ERR_WORK_ORDER_STATE_INVALID": (409, "work order is not in a state that permits this action"),
    "ERR_RETROFIT_STATE_INVALID": (409, "retrofit project is not in a state that permits this action"),
    "ERR_STALE_STORE_VERSION": (412, "store has been modified since it was read"),
    "ERR_STALE_ACCOUNT_VERSION": (412, "utility account has been modified since it was read"),
    "ERR_FOOD_SAFETY_HOLD": (409, "store energy posture blocks this energy program action"),
    "ERR_DISPOSITION_MANDATE_VIOLATION": (422, "product disposition must be DISCARD for this excursion"),
    "ERR_FOOD_SAFETY_DOC_INCOMPLETE": (422, "excursion cannot be closed before disposition and corrective action are documented"),
    "ERR_FAULT_SUPPRESSION_FORBIDDEN": (422, "fault score is too high to suppress"),
    "ERR_STANDARD_NOT_PUBLISHED": (409, "setpoint standard is not published"),
    "ERR_STANDARD_SCOPE_MISMATCH": (422, "setpoint standard scope does not match the store"),
    "ERR_BMS_NOT_COMMISSIONED": (409, "store has no active building management system"),
    "ERR_DR_ENROLLMENT_SUSPENDED": (409, "utility account is suspended from the demand response program"),
    "ERR_TARIFF_SWITCH_IN_PROGRESS": (409, "bill adjustment is blocked while a tariff switch is pending"),
    "ERR_DUPLICATE_STANDARD_SCOPE": (409, "a standard already covers this climate zone, store format and season"),
    "ERR_OVERRIDE_WINDOW_CONFLICT": (409, "lighting override window overlaps an existing override for this zone"),
    "ERR_DR_WINDOW_CONFLICT": (409, "demand response window overlaps or is too close to another event"),
    "ERR_WORK_ORDER_WINDOW_CONFLICT": (409, "work order window overlaps another scheduled order on this equipment"),
    "ERR_BASELINE_DATA_INSUFFICIENT": (422, "no eligible interval available to compute the demand response baseline"),
    "ERR_DEMAND_DATA_MISSING": (422, "no metered demand interval in the billing period"),
    "ERR_CURTAILMENT_NOT_ELAPSED": (422, "curtailment window has not been reached or has not elapsed"),
    "ERR_TARIFF_LOCK_ACTIVE": (409, "account is inside its tariff lock window"),
    "ERR_MV_PERIOD_TOO_SHORT": (422, "measurement period is too short to verify savings"),
    "ERR_OVERRIDE_BUDGET_EXCEEDED": (422, "override would exceed the store's monthly energy allowance"),
    "ERR_WORK_ORDER_CAPACITY_EXCEEDED": (422, "too many work orders already scheduled in this window at this store"),
    "ERR_TARIFF_SWITCH_NOT_JUSTIFIED": (422, "projected savings do not justify the tariff switch"),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        status, default_message = ERROR_CATALOG.get(error_id, (400, "request failed"))
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message
        super().__init__(self.message)


def invalid(detail=None):
    return ApiError("ERR_INVALID_REQUEST", detail)
