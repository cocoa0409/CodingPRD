"""Error catalogue (PRD section 5) and the exception type carrying it."""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Missing or unknown X-User-Role / X-User-ID header"),
    "ERR_FORBIDDEN_ROLE": (403, "Role may not perform this operation"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "Acting user may not both submit and decide this item"),
    "ERR_INVALID_REQUEST": (400, "Malformed or missing field, unknown field, or value outside its declared constraint"),
    "ERR_INVALID_WINDOW_BOUNDS": (400, "Interval start must be strictly before interval end"),
    "ERR_PROJECT_NOT_FOUND": (404, "Project does not exist"),
    "ERR_GRADING_AREA_NOT_FOUND": (404, "Grading area does not exist"),
    "ERR_YARD_ZONE_NOT_FOUND": (404, "Yard zone does not exist"),
    "ERR_DELIVERY_NOT_FOUND": (404, "Delivery does not exist"),
    "ERR_BLOCK_NOT_FOUND": (404, "Block does not exist"),
    "ERR_PILE_NOT_FOUND": (404, "Pile does not exist"),
    "ERR_STRING_CIRCUIT_NOT_FOUND": (404, "String circuit does not exist"),
    "ERR_SUBSTATION_NOT_FOUND": (404, "Substation does not exist"),
    "ERR_OUTAGE_WINDOW_NOT_FOUND": (404, "Outage window does not exist"),
    "ERR_COMMISSIONING_TEST_NOT_FOUND": (404, "Commissioning test does not exist"),
    "ERR_PUNCH_ITEM_NOT_FOUND": (404, "Punch list item does not exist"),
    "ERR_PAYROLL_WEEK_NOT_FOUND": (404, "Payroll week does not exist"),
    "ERR_LABOR_ENTRY_NOT_FOUND": (404, "Labor entry does not exist"),
    "ERR_CROSS_PROJECT_REFERENCE": (422, "Referenced resource belongs to a different project"),
    "ERR_STALE_YARD_ZONE_VERSION": (412, "expected_yard_zone_version does not match the current yard zone version"),
    "ERR_STALE_PROJECT_VERSION": (412, "expected_project_version does not match the current project version"),
    "ERR_GRADING_AREA_NOT_OPEN_FOR_WORK": (409, "Grading area is not in a state that accepts this civil operation"),
    "ERR_DELIVERY_NOT_RESERVED": (409, "Delivery is no longer in RESERVED"),
    "ERR_PILE_NOT_DRIVEABLE": (409, "Pile already has a drive result"),
    "ERR_PILE_NOT_REMEDIABLE": (409, "Pile is not OUT_OF_TOLERANCE or REFUSED"),
    "ERR_BLOCK_PILES_INCOMPLETE": (409, "Block piles are not complete"),
    "ERR_CIRCUIT_STATE_INVALID": (409, "String circuit is not in a state that accepts this operation"),
    "ERR_SUBSTATION_STEP_NOT_SEQUENTIAL": (409, "Substation construction steps may not be skipped or repeated"),
    "ERR_OUTAGE_WINDOW_ALREADY_ANSWERED": (409, "Outage window already has a utility response"),
    "ERR_TEST_STATE_INVALID": (409, "Commissioning test is not in a state that accepts this operation"),
    "ERR_PUNCH_ITEM_STATE_INVALID": (409, "Punch list item is not in a state that accepts this operation"),
    "ERR_PAYROLL_WEEK_LOCKED": (409, "Payroll week is certified and locked"),
    "ERR_LABOR_ENTRY_ALREADY_VOIDED": (409, "Labor entry is already voided"),
    "ERR_MILESTONE_OUT_OF_SEQUENCE": (409, "Milestone claim or decision is out of sequence"),
    "ERR_GRADING_AREA_NOT_ACCEPTED": (409, "Owning grading area has not been accepted"),
    "ERR_BLOCK_NOT_MECHANICALLY_COMPLETE": (409, "Owning block is not mechanically complete"),
    "ERR_SUBSTATION_NOT_ENERGIZED": (422, "No substation of this project is energized"),
    "ERR_PERMIT_NOT_ACTIVE": (422, "Stormwater permit coverage is not active or a BMP deficiency is open"),
    "ERR_RAIN_EVENT_BLACKOUT": (422, "Earthwork is blacked out following a qualifying rain event"),
    "ERR_BMP_INSPECTION_OVERDUE": (422, "Best-management-practice inspection is overdue for this area"),
    "ERR_EARTHWORK_WINDOW_CONFLICT": (409, "Earthwork window collides with an existing window for this area"),
    "ERR_OUTAGE_WINDOW_CONFLICT": (409, "Requested outage collides with an existing window or its switching buffer"),
    "ERR_NO_APPROVED_OUTAGE_WINDOW": (422, "No approved backfeed outage window covers the current instant"),
    "ERR_DISTURBED_ACREAGE_EXCEEDED": (422, "Permitted disturbed acreage would be exceeded"),
    "ERR_YARD_WINDOW_CAPACITY_EXCEEDED": (409, "Laydown zone pallet capacity is exhausted for the requested window"),
    "ERR_TORQUE_TUBE_TOLERANCE_EXCEEDED": (422, "Surveyed torque tube deviation exceeds tolerance"),
    "ERR_INSUFFICIENT_ACCEPTED_MODULES": (422, "Not enough accepted modules have been delivered for the reported installation"),
    "ERR_REMEDIATION_STILL_OUT_OF_TOLERANCE": (422, "Remediated pile still fails embedment or plumb tolerance"),
    "ERR_NO_VALID_TEST_INTERVALS": (422, "Test has no interval that clears the weather filters"),
    "ERR_BLOCKS_NOT_MC_READY": (422, "Project mechanical-completion readiness is BLOCKED"),
    "ERR_REQUIRED_TEST_NOT_PASSED": (422, "Required commissioning test has not passed"),
    "ERR_OPEN_CRITICAL_PUNCH_ITEMS": (422, "Critical punch list items are still open"),
    "ERR_OPEN_PUNCH_ITEMS": (422, "Punch list items are still open"),
    "ERR_TAX_CREDIT_NOT_QUALIFIED": (422, "Project does not qualify for the labor-tied tax credit"),
    "ERR_BELOW_PREVAILING_WAGE": (422, "Paid rate plus fringe is below the prevailing wage determination"),
    "ERR_CHANGE_ORDER_CAP_EXCEEDED": (422, "Cumulative change orders would exceed the contract cap"),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        catalog = ERROR_CATALOG.get(error_id, (400, "Request could not be processed"))
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else catalog[0]
        self.message = message if message else catalog[1]
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def invalid(message=None):
    raise ApiError("ERR_INVALID_REQUEST", message)
