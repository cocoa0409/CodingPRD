"""Error catalogue: error_id -> HTTP status, plus the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


ERROR_STATUS = {
    # --- authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ACCOUNT_SCOPE_VIOLATION": 403,
    "ERR_TECHNICIAN_NOT_ASSIGNED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request shape
    "ERR_INVALID_REQUEST": 400,
    # --- existence
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_CHEMICAL_LOT_NOT_FOUND": 404,
    "ERR_PART_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_BALANCE_RECORD_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_GLYCOL_LOOP_NOT_FOUND": 404,
    "ERR_READING_NOT_FOUND": 404,
    # --- optimistic concurrency
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_STALE_LINE_VERSION": 412,
    # --- own-state / cross-entity state
    "ERR_VISIT_NOT_SCHEDULED": 409,
    "ERR_VISIT_NOT_IN_PROGRESS": 409,
    "ERR_WORK_NOT_COMPLETE": 409,
    "ERR_CYCLE_ALREADY_VOIDED": 409,
    "ERR_BALANCE_RECORD_NOT_PROPOSED": 409,
    "ERR_VERIFICATION_ALREADY_RECORDED": 409,
    "ERR_COMPLAINT_ALREADY_CLOSED": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_NO_ACTIVE_CONTRACT": 409,
    "ERR_TECHNICIAN_INACTIVE": 409,
    "ERR_LINE_OUT_OF_SERVICE": 409,
    "ERR_CHEMICAL_LOT_UNAVAILABLE": 409,
    "ERR_VISIT_ALREADY_SETTLED": 409,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    # --- referential coherence
    "ERR_LINE_ACCOUNT_MISMATCH": 422,
    "ERR_CHEMICAL_TYPE_MISMATCH": 422,
    "ERR_PART_TYPE_MISMATCH": 422,
    # --- temporal / scheduling
    "ERR_VISIT_DATE_IN_PAST": 422,
    "ERR_SCHEDULE_LEAD_EXCEEDED": 422,
    "ERR_OUTSIDE_ACCESS_WINDOW": 422,
    "ERR_VENUE_SLOT_CONFLICT": 409,
    "ERR_TECHNICIAN_ROUTE_CONFLICT": 409,
    # --- safety
    "ERR_CHEMICAL_LOT_EXPIRED": 422,
    "ERR_TECHNICIAN_NOT_CAUSTIC_CERTIFIED": 422,
    "ERR_GLYCOL_ALARM_BLOCK": 422,
    "ERR_CHEMICAL_PARITY_VIOLATION": 422,
    "ERR_CLEANING_TOO_EARLY": 422,
    # --- business constraints
    "ERR_DUPLICATE_LINE_NUMBER": 409,
    "ERR_DUPLICATE_LOT_CODE": 409,
    "ERR_CONTRACT_LINE_LIMIT_EXCEEDED": 422,
    "ERR_CONTRACT_NOT_YET_EFFECTIVE": 422,
    "ERR_VISIT_START_TOO_EARLY": 422,
    "ERR_WAIVER_TOO_EARLY": 422,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_REOPEN_WINDOW_CLOSED": 422,
    "ERR_REOPEN_LIMIT_EXCEEDED": 422,
    "ERR_DIAGNOSTIC_ROUNDS_EXHAUSTED": 422,
    "ERR_NO_WORK_RECORDED": 422,
    "ERR_LINE_STILL_NON_COMPLIANT": 409,
    "ERR_LINE_COMPLIANCE_UNRESOLVED": 409,
    "ERR_ACCOUNT_HAS_OPEN_VISITS": 409,
    "ERR_LOT_RELEASE_BLOCKED": 409,
    "ERR_NO_GLYCOL_SYSTEM": 422,
    "ERR_PRESSURE_OUT_OF_BALANCE": 422,
    "ERR_GAS_BLEND_MISMATCH": 422,
    # --- fiscal / stock
    "ERR_CHEMICAL_INSUFFICIENT_VOLUME": 422,
    "ERR_PART_OUT_OF_STOCK": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is unknown.",
    "ERR_UNAUTHORIZED": "The acting role may not perform this operation.",
    "ERR_ACCOUNT_SCOPE_VIOLATION": "The acting venue manager is not scoped to this service account.",
    "ERR_TECHNICIAN_NOT_ASSIGNED": "The acting technician is not assigned to this work.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting auditor may not close work they escalated.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
    "ERR_ACCOUNT_NOT_FOUND": "ServiceAccount not found.",
    "ERR_CONTRACT_NOT_FOUND": "ServiceContract not found.",
    "ERR_LINE_NOT_FOUND": "BeerLine not found.",
    "ERR_TECHNICIAN_NOT_FOUND": "Technician not found.",
    "ERR_CHEMICAL_LOT_NOT_FOUND": "ChemicalLot not found.",
    "ERR_PART_NOT_FOUND": "PartCatalogItem not found.",
    "ERR_PROGRAM_NOT_FOUND": "BrewerProgram not found.",
    "ERR_VISIT_NOT_FOUND": "ServiceVisit not found.",
    "ERR_CYCLE_NOT_FOUND": "CleaningCycle not found.",
    "ERR_BALANCE_RECORD_NOT_FOUND": "BalanceRecord not found.",
    "ERR_INSPECTION_NOT_FOUND": "ComponentInspection not found.",
    "ERR_COMPLAINT_NOT_FOUND": "QualityComplaint not found.",
    "ERR_GLYCOL_LOOP_NOT_FOUND": "GlycolLoop not found.",
    "ERR_READING_NOT_FOUND": "CoolerReading not found.",
    "ERR_STALE_ACCOUNT_VERSION": "expected_account_version does not match the stored account version.",
    "ERR_STALE_LINE_VERSION": "expected_line_version does not match the stored line version.",
}


def raise_error(error_id, message=None):
    raise ApiError(error_id, message)
