"""Error catalogue and the ApiError exception carried through the ladder."""

ERROR_CATALOG = {
    # -- authentication / authorisation -------------------------------------
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are missing or the role is unknown"),
    "ERR_ROLE_FORBIDDEN": (403, "The presented role may not perform this operation"),
    "ERR_CLUB_SCOPE_FORBIDDEN": (403, "The club manager may only act inside its own club"),
    "ERR_TECHNICIAN_NOT_ASSIGNED": (403, "The technician is not assigned to this work item"),
    "ERR_INSPECTOR_NOT_CERTIFIED": (403, "The acting principal is not a certified safety inspector"),
    # -- existence ----------------------------------------------------------
    "ERR_CLUB_NOT_FOUND": (404, "Club not found"),
    "ERR_MODEL_NOT_FOUND": (404, "Equipment model not found"),
    "ERR_EQUIPMENT_NOT_FOUND": (404, "Equipment not found"),
    "ERR_CONTRACT_NOT_FOUND": (404, "Service contract not found"),
    "ERR_TECHNICIAN_NOT_FOUND": (404, "Technician not found"),
    "ERR_VISIT_NOT_FOUND": (404, "Preventive visit not found"),
    "ERR_CALL_NOT_FOUND": (404, "Service call not found"),
    "ERR_ASSIGNMENT_NOT_FOUND": (404, "Technician assignment not found"),
    "ERR_PART_NOT_FOUND": (404, "Part catalog entry not found"),
    "ERR_PART_ORDER_NOT_FOUND": (404, "Part order not found"),
    "ERR_DOWNTIME_EVENT_NOT_FOUND": (404, "Downtime event not found"),
    "ERR_QUOTE_NOT_FOUND": (404, "Renewal quote not found"),
    # -- request shape ------------------------------------------------------
    "ERR_INVALID_REQUEST": (400, "The request is malformed or violates a field constraint"),
    # -- optimistic concurrency --------------------------------------------
    "ERR_STALE_CONTRACT_VERSION": (412, "The supplied contract version is stale"),
    # -- state --------------------------------------------------------------
    "ERR_CONTRACT_INVALID_STATE": (409, "The contract is not in a state that allows this transition"),
    "ERR_CONTRACT_NOT_ACTIVE": (409, "The contract is not ACTIVE"),
    "ERR_CALL_INVALID_STATE": (409, "The service call is not in a state that allows this transition"),
    "ERR_VISIT_INVALID_STATE": (409, "The preventive visit is not in a state that allows this transition"),
    "ERR_SAFETY_DOC_INVALID_STATE": (409, "The safety document is not in a state that allows this transition"),
    "ERR_PART_ORDER_INVALID_STATE": (409, "The part order is not in a state that allows this transition"),
    "ERR_DOWNTIME_INVALID_STATE": (409, "The downtime event is not in a state that allows this transition"),
    "ERR_ASSIGNMENT_INVALID_STATE": (409, "The assignment is not in a state that allows this transition"),
    "ERR_QUOTE_NOT_ISSUED": (409, "The quote is not open for a decision"),
    "ERR_QUOTE_EXPIRED": (409, "The quote has expired"),
    # -- safety and compliance ---------------------------------------------
    "ERR_SAFETY_LOCKOUT_OPEN": (409, "A safety lockout is open"),
    "ERR_SAFETY_CLEARANCE_REQUIRED": (422, "A certified safety clearance signature is required"),
    "ERR_SAFETY_CERTIFICATION_REQUIRED": (422, "A certified safety inspector is required"),
    "ERR_SEGREGATION_OF_DUTIES": (409, "The same technician may not perform both duties"),
    "ERR_INJURY_SEVERITY_MISMATCH": (422, "An injury report requires CRITICAL severity"),
    "ERR_SAFETY_CRITICAL_FAIL_BLOCKS_COMPLETION": (409, "An unresolved safety-critical failure blocks completion"),
    # -- referential integrity ---------------------------------------------
    "ERR_EQUIPMENT_CLUB_MISMATCH": (422, "The machine does not belong to the contract's club"),
    "ERR_PART_MODEL_MISMATCH": (422, "The part does not belong to the machine's model"),
    "ERR_TECHNICIAN_REGION_MISMATCH": (422, "The technician does not serve the club's region"),
    "ERR_TECHNICIAN_SKILL_MISMATCH": (422, "The technician lacks the required skill category"),
    "ERR_TECHNICIAN_OFF_DUTY": (409, "The technician is OFF_DUTY"),
    # -- temporal -----------------------------------------------------------
    "ERR_VISIT_WINDOW_INVALID": (422, "The visit window is invalid"),
    "ERR_CLUB_VISIT_CAPACITY": (409, "The club's concurrent visit capacity is exhausted"),
    "ERR_TECHNICIAN_WINDOW_CONFLICT": (409, "The technician's calendar conflicts with this window"),
    "ERR_TECHNICIAN_CAPACITY_EXCEEDED": (409, "The technician's committed minutes ceiling would be exceeded"),
    # -- domain rules -------------------------------------------------------
    "ERR_ACTIVE_CONTRACT_EXISTS": (409, "The club already holds a live contract"),
    "ERR_SERIAL_DUPLICATE": (409, "The serial number already exists in the installed base"),
    "ERR_TIER_PARTS_MISMATCH": (422, "The parts inclusion is not permitted at this coverage tier"),
    "ERR_PM_FREQUENCY_BELOW_TIER": (422, "The planned visit frequency is below the tier minimum"),
    "ERR_USAGE_REGRESSION": (422, "The usage reading regresses below the recorded total"),
    "ERR_CHECKLIST_ITEM_UNKNOWN": (422, "The checklist item is not part of this visit"),
    "ERR_CHECKLIST_INCOMPLETE": (409, "The checklist still has unresolved items"),
    "ERR_DUPLICATE_OPEN_CALL": (409, "The machine already has a live service call"),
    "ERR_PARTS_HOLD_LIMIT": (409, "The parts-hold limit for this call is exhausted"),
    "ERR_PART_OUT_OF_STOCK": (409, "The requested source bucket cannot satisfy the quantity"),
    "ERR_PART_SOURCE_UNAVAILABLE": (422, "The requested source is not available for this part"),
    "ERR_NO_ELIGIBLE_TECHNICIAN": (422, "No technician satisfies the routing selector"),
    "ERR_UNRESOLVED_PART_ORDER": (409, "An allocated part order is still outstanding"),
    "ERR_FLEET_EMPTY": (422, "The club has no machines to price"),
    "ERR_PERIOD_ALREADY_RECONCILED": (409, "The period has already been reconciled or has nothing to reconcile"),
    # -- fiscal -------------------------------------------------------------
    "ERR_PARTS_ALLOWANCE_EXHAUSTED": (409, "The parts allowance is exhausted"),
    "ERR_ALLOWANCE_ADJUSTMENT_INVALID": (422, "The allowance adjustment would drive a balance negative"),
    "ERR_INVENTORY_ADJUSTMENT_INVALID": (422, "The inventory adjustment would drive a bucket negative"),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        status, default_message = ERROR_CATALOG.get(error_id, (400, "Invalid request"))
        self.error_id = error_id
        self.message = message or default_message
        self.http_status = status
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
