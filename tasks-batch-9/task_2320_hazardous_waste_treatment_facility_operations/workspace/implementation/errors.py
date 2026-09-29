"""Error catalog (SCAFFOLD 1.6 / PRD 5) and the ApiError exception."""

CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Missing or malformed authentication headers"),
    "ERR_ROLE_NOT_PERMITTED": (403, "Role is not permitted to perform this operation"),
    "ERR_GENERATOR_SCOPE_VIOLATION": (403, "Generator callers may only address their own rows"),
    "ERR_INVALID_REQUEST": (400, "Request body or query parameters are invalid"),
    "ERR_FACILITY_NOT_FOUND": (404, "Facility does not exist"),
    "ERR_GENERATOR_NOT_FOUND": (404, "Generator does not exist"),
    "ERR_WASTE_PROFILE_NOT_FOUND": (404, "Waste profile does not exist"),
    "ERR_MANIFEST_NOT_FOUND": (404, "Manifest does not exist"),
    "ERR_STORAGE_UNIT_NOT_FOUND": (404, "Storage unit does not exist"),
    "ERR_CONTAINER_NOT_FOUND": (404, "Container does not exist"),
    "ERR_TREATMENT_BATCH_NOT_FOUND": (404, "Treatment batch does not exist"),
    "ERR_RESOURCE_NOT_FOUND": (404, "Addressed resource does not exist"),
    "ERR_REFERENCE_NOT_FOUND": (404, "A referenced row in the request body does not exist"),
    "ERR_STALE_VERSION": (412, "Parent version has advanced since it was read"),
    "ERR_FACILITY_SCOPE_MISMATCH": (409, "Referenced rows belong to different facilities"),
    "ERR_INVALID_STATE": (409, "Entity is not in a state that allows this operation"),
    "ERR_UNIT_POSTURE_BLOCKED": (409, "Storage unit posture does not allow this operation"),
    "ERR_PERMIT_NOT_ACTIVE": (403, "Facility permit is not active"),
    "ERR_GENERATOR_SUSPENDED": (409, "Generator is suspended or terminated"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The same user may not perform both steps"),
    "ERR_PROFILE_NOT_APPROVED": (409, "Waste profile is not approved"),
    "ERR_PROFILE_EXPIRED": (409, "Waste profile requires recertification"),
    "ERR_SAMPLE_LIMIT_EXCEEDED": (409, "The profile has exhausted its verification sample attempts"),
    "ERR_ACCEPTANCE_CRITERIA_FAILED": (
        422, "A received line's waste profile no longer satisfies the acceptance criteria"),
    "ERR_INCOMPATIBLE_SEGREGATION": (409, "Container is incompatible with the unit or its current contents"),
    "ERR_LABEL_CODE_MISMATCH": (422, "Label waste codes do not match the profile"),
    "ERR_LABEL_INCOMPLETE": (422, "Container label is incomplete"),
    "ERR_CONTAINER_OVERFILLED": (422, "Net weight exceeds the permitted fill fraction"),
    "ERR_METHOD_NOT_PERMITTED": (403, "Treatment method is not authorized by the permit"),
    "ERR_LDR_STANDARD_NOT_MET": (409, "Residue has not met the land disposal restriction standard"),
    "ERR_TEN_DAY_LIMIT_EXCEEDED": (409, "Ten-day transfer accumulation limit exceeded"),
    "ERR_INSPECTION_OVERDUE": (409, "Unit inspection is overdue"),
    "ERR_REPAIR_ATTEMPT_LATE": (409, "Repair action is past its deadline"),
    "ERR_LEAK_PERSISTS": (409, "Monitored concentration is still at or above the leak definition"),
    "ERR_DELAY_JUSTIFICATION_INVALID": (422, "Delay of repair justification or deadline is not allowed"),
    "ERR_DISCREPANCY_REPORT_OVERDUE": (
        409, "Discrepancy exception report deadline has passed or the report was never filed"),
    "ERR_CORRECTIVE_ACTION_OVERDUE": (409, "An SNC corrective action is overdue"),
    "ERR_TREATMENT_WINDOW_CONFLICT": (409, "Treatment window conflicts with another batch in the unit"),
    "ERR_FACILITY_CONCURRENCY_EXCEEDED": (409, "Permit cap on concurrent treatment batches reached"),
    "ERR_AISLE_CLEARANCE_VIOLATION": (409, "Placement would reduce the aisle below the required clearance"),
    "ERR_DUPLICATE_MANIFEST_NUMBER": (
        409, "A uniqueness constraint is violated (manifest tracking number, EPA id or unit code)"),
    "ERR_LINE_MASS_OVER_ALLOCATED": (422, "Container mass exceeds the mass remaining on the manifest line"),
    "ERR_MASS_BALANCE_INVALID": (422, "Residue mass exceeds the batch input mass"),
    "ERR_INSPECTION_FREQUENCY_INVALID": (422, "Inspection frequency exceeds the ceiling for the unit type"),
    "ERR_STORAGE_CAPACITY_EXCEEDED": (409, "Permitted storage capacity would be exceeded"),
    "ERR_FINANCIAL_ASSURANCE_SHORTFALL": (402, "Posted financial assurance does not cover the required amount"),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        status, default_message = CATALOG.get(error_id, (400, "Request is invalid"))
        self.error_id = error_id
        self.message = message or default_message
        self.http_status = status
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
