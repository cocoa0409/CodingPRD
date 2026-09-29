"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message if message else DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status if http_status else ERROR_STATUS.get(error_id, 400)


ERROR_STATUS = {
    # authn / authz
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_VALIDATION": 422,
    "ERR_ACTING_WORKER_NOT_FOUND": 404,
    "ERR_ACTOR_MEDICALLY_REMOVED": 403,
    "ERR_ACTOR_JOB_CLASS_MISMATCH": 403,
    # existence
    "ERR_PLANT_NOT_FOUND": 404,
    "ERR_CELL_DESIGN_NOT_FOUND": 404,
    "ERR_WORKER_NOT_FOUND": 404,
    "ERR_FORMATION_BAY_NOT_FOUND": 404,
    "ERR_TEST_CHAMBER_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_ASSEMBLY_NOT_FOUND": 404,
    "ERR_FORMATION_RUN_NOT_FOUND": 404,
    "ERR_CAPACITY_TEST_NOT_FOUND": 404,
    "ERR_CHARGER_NOT_FOUND": 404,
    "ERR_SIZING_REQUEST_NOT_FOUND": 404,
    "ERR_BATTERY_UNIT_NOT_FOUND": 404,
    # uniqueness
    "ERR_DUPLICATE_CODE": 409,
    # concurrency
    "ERR_STALE_LOT_VERSION": 412,
    "ERR_STALE_BATTERY_UNIT_VERSION": 412,
    # state legality
    "ERR_DESIGN_STATE_INVALID": 409,
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_RUN_STATE_INVALID": 409,
    "ERR_ASSEMBLY_STATE_INVALID": 409,
    "ERR_ASSEMBLY_AXIS_ALREADY_RECORDED": 409,
    "ERR_CAPACITY_TEST_STATE_INVALID": 409,
    "ERR_WARRANTY_STATE_INVALID": 409,
    "ERR_WARRANTY_ALREADY_SETTLED": 409,
    "ERR_CORE_STATE_INVALID": 409,
    "ERR_WORKER_NOT_REMOVED": 409,
    "ERR_SIZING_REQUEST_STATE_INVALID": 409,
    "ERR_CYCLE_LIFE_SAMPLE_MISSING": 409,
    # safety / licensing / posture
    "ERR_PLANT_FROZEN": 409,
    "ERR_PLANT_RESTRICTED": 409,
    "ERR_LOT_ENV_HELD": 409,
    "ERR_CHEMISTRY_NOT_LICENSED": 409,
    "ERR_CLEARANCE_EVIDENCE_MISSING": 409,
    "ERR_EVENT_TIME_OUT_OF_RANGE": 422,
    # segregation of duties
    "ERR_SEGREGATION_OF_DUTIES": 409,
    # referential coherence
    "ERR_PLANT_SCOPE_MISMATCH": 409,
    "ERR_DESIGN_NOT_APPROVED": 409,
    "ERR_ASSEMBLY_NOT_CERTIFIED": 409,
    "ERR_BAY_UNAVAILABLE": 409,
    "ERR_CHAMBER_UNAVAILABLE": 409,
    "ERR_PLATE_TYPE_INCOMPATIBLE": 422,
    # windows / capacity / limits
    "ERR_WINDOW_INVALID": 422,
    "ERR_BAY_WINDOW_CONFLICT": 409,
    "ERR_CHAMBER_CAPACITY_EXCEEDED": 409,
    "ERR_CONNECTION_COUNT_MISMATCH": 422,
    "ERR_SAMPLING_INCOMPLETE": 409,
    "ERR_ACCEPTANCE_EXCEEDED": 409,
    "ERR_RETEST_LIMIT_REACHED": 409,
    "ERR_REWORK_LIMIT_REACHED": 409,
    "ERR_CORE_MASS_VARIANCE_EXCEEDED": 422,
    "ERR_CORE_NOT_APPLICABLE": 409,
    "ERR_NO_ELIGIBLE_CELL_DESIGN": 422,
    "ERR_NO_CHARGER_MATCH": 422,
    # fiscal / budget
    "ERR_EMISSION_BUDGET_EXCEEDED": 409,
    "ERR_LEAD_INVENTORY_INSUFFICIENT": 409,
    "ERR_METERED_ENERGY_OUT_OF_RANGE": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers",
    "ERR_ROLE_NOT_PERMITTED": "Role is not permitted to perform this operation",
    "ERR_VALIDATION": "Request payload failed validation",
    "ERR_ACTING_WORKER_NOT_FOUND": "Acting worker does not exist",
    "ERR_ACTOR_MEDICALLY_REMOVED": "Acting worker is medically removed",
    "ERR_ACTOR_JOB_CLASS_MISMATCH": "Acting worker job class may not perform this operation",
    "ERR_PLANT_NOT_FOUND": "Plant not found",
    "ERR_CELL_DESIGN_NOT_FOUND": "Cell design not found",
    "ERR_WORKER_NOT_FOUND": "Worker not found",
    "ERR_FORMATION_BAY_NOT_FOUND": "Formation bay not found",
    "ERR_TEST_CHAMBER_NOT_FOUND": "Test chamber not found",
    "ERR_LOT_NOT_FOUND": "Production lot not found",
    "ERR_ASSEMBLY_NOT_FOUND": "Battery assembly not found",
    "ERR_FORMATION_RUN_NOT_FOUND": "Formation run not found",
    "ERR_CAPACITY_TEST_NOT_FOUND": "Capacity test not found",
    "ERR_CHARGER_NOT_FOUND": "Charger not found",
    "ERR_SIZING_REQUEST_NOT_FOUND": "Fleet sizing request not found",
    "ERR_BATTERY_UNIT_NOT_FOUND": "Battery unit not found",
    "ERR_DUPLICATE_CODE": "Business identifier already exists in its uniqueness scope",
}
