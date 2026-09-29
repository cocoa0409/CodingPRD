"""Error catalogue (PRD section 5) and the exception type carrying it."""

ERROR_CATALOG = {
    "ERR_VALIDATION": (422, "Request body or query parameters are malformed, missing a required field, or carry an unknown enum value"),
    "ERR_UNAUTHORIZED": (403, "The calling role may not perform this operation"),
    "ERR_BUILDING_NOT_FOUND": (404, "Building does not exist"),
    "ERR_FLOOR_NOT_FOUND": (404, "Floor does not exist"),
    "ERR_ASSESSMENT_NOT_FOUND": (404, "Suitability assessment does not exist"),
    "ERR_SCOPE_ITEM_NOT_FOUND": (404, "Conversion scope item does not exist"),
    "ERR_TENANT_NOT_FOUND": (404, "Tenant does not exist"),
    "ERR_LEASE_NOT_FOUND": (404, "Lease does not exist"),
    "ERR_PROPOSAL_NOT_FOUND": (404, "TI proposal does not exist"),
    "ERR_PROJECT_NOT_FOUND": (404, "Fit-out project does not exist"),
    "ERR_PHASE_NOT_FOUND": (404, "Phase package does not exist"),
    "ERR_RESERVATION_NOT_FOUND": (404, "Capacity reservation does not exist"),
    "ERR_PERMIT_NOT_FOUND": (404, "Hazardous material use permit does not exist"),
    "ERR_AMENITY_NOT_FOUND": (404, "Shared amenity does not exist"),
    "ERR_ALLOCATION_NOT_FOUND": (404, "Amenity allocation does not exist"),
    "ERR_COMMISSIONING_RECORD_NOT_FOUND": (404, "Commissioning record does not exist"),
    "ERR_STALE_BUILDING_VERSION": (412, "expected_building_version does not match the building's current version"),
    "ERR_STALE_LEASE_VERSION": (412, "expected_lease_version does not match the lease's current version"),
    "ERR_INVALID_BUILDING_STATE": (409, "The building's suitability_state does not permit this operation"),
    "ERR_INVALID_ASSESSMENT_STATE": (409, "The assessment's status does not permit this operation"),
    "ERR_ASSESSMENT_ALREADY_OPEN": (409, "An assessment for this building is already in progress"),
    "ERR_RETURN_NOTE_REQUIRED": (422, "A return_note is required when returning an assessment"),
    "ERR_INVALID_SCOPE_ITEM_STATE": (409, "The conversion scope item is already complete"),
    "ERR_DUPLICATE_SCOPE_DISCIPLINE": (409, "A conversion scope item already exists for this discipline"),
    "ERR_CONVERSION_SCOPE_INCOMPLETE": (409, "The building has no lab exhaust conversion scope item"),
    "ERR_BUILDING_NOT_CONVERSION_APPROVED": (409, "The building has not been approved for lab conversion"),
    "ERR_EXHAUST_SCOPE_INCOMPLETE": (409, "The building's lab exhaust conversion scope is not complete"),
    "ERR_DUPLICATE_FLOOR_NUMBER": (409, "A floor with this number already exists in the building"),
    "ERR_FLOOR_NOT_IN_PREMISES": (422, "The floor does not belong to the referenced building or premises"),
    "ERR_INVALID_LEASE_STATE": (409, "The lease's status does not permit this operation"),
    "ERR_INVALID_PROPOSAL_STATE": (409, "The proposal is no longer open"),
    "ERR_NOT_YOUR_TURN": (409, "The other party holds the open negotiation round"),
    "ERR_SELF_ACCEPT_FORBIDDEN": (403, "A proposal cannot be accepted by its own author or party"),
    "ERR_PROPOSAL_EXPIRED": (409, "The proposal's acceptance window has elapsed"),
    "ERR_NEGOTIATION_ROUND_LIMIT": (409, "The negotiation round limit has been reached"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The user who negotiated or accepted the terms may not execute the lease"),
    "ERR_ESCROW_DEPOSIT_INSUFFICIENT": (422, "The restoration escrow held is below the required amount"),
    "ERR_TI_ALLOWANCE_EXHAUSTED": (409, "No committed tenant improvement allowance is available to draw"),
    "ERR_RESTORATION_ALREADY_SETTLED": (409, "The lease is not awaiting restoration settlement"),
    "ERR_PHASES_NOT_QUIESCED": (409, "Phase packages are still scheduled, held, blocked or in progress"),
    "ERR_INVALID_PERMIT_STATE": (409, "The project's permit_status does not permit this operation"),
    "ERR_INVALID_PROJECT_STATE": (409, "The project's construction_status does not permit this operation"),
    "ERR_PROJECT_NOT_PERMITTED": (409, "The fit-out project's construction permit has not been issued"),
    "ERR_PREDECESSOR_NOT_IN_PROJECT": (422, "The predecessor phase belongs to a different project"),
    "ERR_PREDECESSOR_NOT_COMPLETE": (409, "The predecessor phase is not complete"),
    "ERR_DUPLICATE_PHASE_SEQUENCE": (409, "A phase with this sequence number already exists on the project"),
    "ERR_SHUTDOWN_AMENITY_REQUIRED": (422, "A shutdown phase must name the affected shared amenity"),
    "ERR_INVALID_PHASE_STATE": (409, "The phase's status does not permit this operation"),
    "ERR_INVALID_WINDOW": (422, "window_start must be strictly before window_end"),
    "ERR_VIBRATION_WINDOW_CONFLICT": (409, "The window conflicts with vibration-generating work on the same floor"),
    "ERR_WINDOW_OUTSIDE_DELIVERY_TERM": (422, "The window falls outside the lease's delivery term"),
    "ERR_SHUTDOWN_CONFLICTS_AMENITY": (409, "The shutdown window overlaps a confirmed shared amenity allocation"),
    "ERR_HOLD_REASON_REQUIRED": (422, "A hold_reason is required to place a phase on vibration hold"),
    "ERR_EXHAUST_CAPACITY_EXCEEDED": (409, "The requested lab exhaust exceeds the building's available capacity"),
    "ERR_POWER_CAPACITY_EXCEEDED": (409, "The requested emergency power exceeds the building's available capacity"),
    "ERR_INVALID_RESERVATION_STATE": (409, "The reservation's status does not permit this operation"),
    "ERR_CONTROL_AREA_OUT_OF_RANGE": (422, "control_area_index exceeds the control areas allowed on this floor"),
    "ERR_CONTROL_AREA_MAQ_EXCEEDED": (409, "The quantity exceeds the control area's maximum allowable quantity"),
    "ERR_INVALID_PERMIT_DECISION": (409, "The permit's status does not permit this decision"),
    "ERR_DECISION_REASON_REQUIRED": (422, "A decision_reason is required to deny or revoke a permit"),
    "ERR_AMENITY_NOT_IN_BUILDING": (422, "The amenity belongs to a different building than the project"),
    "ERR_AMENITY_CAPACITY_EXCEEDED": (409, "The amenity's concurrent capacity would be exceeded in the requested window"),
    "ERR_INVALID_ALLOCATION_STATE": (409, "The allocation's status does not permit this operation"),
    "ERR_SCRIPT_NOT_REQUIRED": (422, "This script is not required for the tenant's research type"),
    "ERR_DUPLICATE_COMMISSIONING_SCRIPT": (409, "An open or passed record already exists for this script"),
    "ERR_INVALID_COMMISSIONING_STATE": (409, "The commissioning record already has a result"),
    "ERR_COMMISSIONING_INCOMPLETE": (409, "The project has not reached substantial completion"),
    "ERR_WITNESS_CONFLICT": (403, "The technician who executed a script may not witness its result"),
}


class ApiError(Exception):
    """Domain failure carrying an error_id from the catalogue."""

    def __init__(self, error_id, message=None):
        status, default_message = ERROR_CATALOG.get(error_id, (400, "Request failed"))
        super().__init__(message or default_message)
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message


def fail(error_id, message=None):
    raise ApiError(error_id, message)
