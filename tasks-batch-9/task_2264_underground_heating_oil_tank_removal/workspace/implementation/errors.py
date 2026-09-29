"""Error catalog — §1.6 of SCAFFOLD.yaml / §5 of PRD.md."""

ERROR_CATALOG = {
    # --- auth / authorization -------------------------------------------------
    "ERR_UNAUTHENTICATED": (401, "X-User-ID or X-User-Role header missing or invalid."),
    "ERR_ROLE_NOT_PERMITTED": (403, "The acting role is not permitted to perform this operation."),
    "ERR_NOT_RESOURCE_OWNER": (403, "The acting principal does not own the addressed resource."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The signer of an NFA letter must differ from its drafter."),
    # --- existence -----------------------------------------------------------
    "ERR_PROPERTY_NOT_FOUND": (404, "Property not found."),
    "ERR_TANK_PROJECT_NOT_FOUND": (404, "Tank project not found."),
    "ERR_DISCLOSURE_NOT_FOUND": (404, "Homeowner disclosure not found."),
    "ERR_PERMIT_NOT_FOUND": (404, "Permit not found."),
    "ERR_CREW_NOT_FOUND": (404, "Crew not found."),
    "ERR_WORK_ORDER_NOT_FOUND": (404, "Decommission work order not found."),
    "ERR_LABORATORY_NOT_FOUND": (404, "Laboratory not found."),
    "ERR_SOIL_SAMPLE_NOT_FOUND": (404, "Soil sample not found."),
    "ERR_CHANGE_ORDER_NOT_FOUND": (404, "Remediation change order not found."),
    "ERR_CLAIM_NOT_FOUND": (404, "Trust-fund claim not found."),
    "ERR_NFA_LETTER_NOT_FOUND": (404, "NFA letter not found."),
    "ERR_INSURANCE_NOTIFICATION_NOT_FOUND": (404, "Insurance notification not found."),
    # --- shape ---------------------------------------------------------------
    "ERR_INVALID_REQUEST": (422, "The request body is invalid."),
    "ERR_INVALID_PAGINATION": (422, "limit must be within [1, 100] and offset must be >= 0."),
    "ERR_METHOD_OVERRIDE_REASON_REQUIRED": (
        422, "method_override_reason is required when method differs from the recommended method."),
    "ERR_CLOSING_DATE_IN_PAST": (422, "closing_date must not be in the past at issuance."),
    # --- concurrency ---------------------------------------------------------
    "ERR_STALE_PROJECT_VERSION": (412, "expected_project_version does not match the project's current version."),
    # --- state ---------------------------------------------------------------
    "ERR_PROJECT_STATE_INVALID": (409, "The tank project is not in a state that allows this operation."),
    "ERR_DISCLOSURE_STATE_INVALID": (409, "The disclosure is not in a state that allows this operation."),
    "ERR_PERMIT_STATE_INVALID": (409, "The permit is not in a state that allows this operation."),
    "ERR_WORK_ORDER_STATE_INVALID": (409, "The work order is not in a state that allows this operation."),
    "ERR_SAMPLE_STATE_INVALID": (409, "The soil sample is not in a state that allows this operation."),
    "ERR_CHANGE_ORDER_STATE_INVALID": (409, "The change order is not in a state that allows this operation."),
    "ERR_CLAIM_STATE_INVALID": (409, "The trust-fund claim is not in a state that allows this operation."),
    "ERR_NFA_STATE_INVALID": (409, "The NFA letter is not in a state that allows this operation."),
    # --- regulatory safety ---------------------------------------------------
    "ERR_NO_TANK_LOCATED": (409, "The sweep survey located no tank."),
    "ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE": (
        409, "No issued fire-marshal notification is effective yet for this project."),
    "ERR_PERMIT_NOT_ISSUED": (409, "The project has no issued municipal decommissioning permit."),
    "ERR_PERMIT_EXPIRED": (409, "The municipal decommissioning permit has expired."),
    "ERR_DISCLOSURE_EXPIRED": (409, "The disclosure response window has expired."),
    "ERR_DISCLOSURE_NOT_ACKNOWLEDGED": (
        409, "A CONTAMINATION_FINDINGS disclosure must be acknowledged first."),
    "ERR_LAB_NOT_ACCREDITED": (409, "The laboratory is not accredited."),
    "ERR_NFA_BLOCKED": (409, "The project still has outstanding NFA blockers."),
    # --- referential ---------------------------------------------------------
    "ERR_SUPERSEDE_TARGET_INVALID": (
        409, "supersedes_change_order_id must name an APPROVED change order on the same project."),
    "ERR_RETEST_TARGET_INVALID": (
        409, "retest_of_sample_id must name an INVALIDATED sample on the same project."),
    # --- temporal ------------------------------------------------------------
    "ERR_CREW_BOOKING_CONFLICT": (409, "The crew booking collides with an existing booking."),
    "ERR_LAB_CAPACITY_EXCEEDED": (409, "The laboratory has no free analysis capacity."),
    "ERR_HOLDING_TIME_EXCEEDED": (409, "The sample holding time has been exceeded."),
    # --- fiscal --------------------------------------------------------------
    "ERR_EXCAVATION_LIMIT_EXCEEDED": (409, "Approval would exceed the project's excavation limit."),
    "ERR_CLAIM_NOT_ELIGIBLE": (409, "The claim has no eligible reimbursement amount."),
    # --- uniqueness / quota --------------------------------------------------
    "ERR_DUPLICATE_DISCLOSURE": (409, "A PENDING disclosure of this kind already exists on the project."),
    "ERR_WORK_ORDER_ALREADY_OPEN": (409, "The project already has an open work order."),
    "ERR_DUPLICATE_FINAL_CLAIM": (409, "The project already has a live FINAL_SETTLEMENT claim."),
    "ERR_INFO_REQUEST_LIMIT_REACHED": (409, "The information-request limit has been reached."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        http_status, default_message = ERROR_CATALOG[error_id]
        super().__init__(message or default_message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or default_message
