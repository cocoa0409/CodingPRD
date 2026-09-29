"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        entry = ERROR_CATALOG.get(error_id)
        if entry is None:
            entry = (400, "Request could not be processed.")
        self.http_status = http_status if http_status is not None else entry[0]
        self.message = message if message is not None else entry[1]


ERROR_CATALOG = {
    # structural / authorization
    "ERR_VALIDATION": (400, "The request body is malformed, is missing a required field, or carries an out-of-domain value."),
    "ERR_UNAUTHORIZED": (403, "The acting role is not permitted to perform this operation."),
    "ERR_CLOCK_NOT_MONOTONIC": (409, "The logical clock cannot move backwards."),
    # not found
    "ERR_PRESCRIBER_NOT_FOUND": (404, "No prescriber with that id."),
    "ERR_PATIENT_NOT_FOUND": (404, "No patient with that id."),
    "ERR_INSURANCE_PLAN_NOT_FOUND": (404, "No insurance plan with that id."),
    "ERR_LENS_DESIGN_NOT_FOUND": (404, "No lens design with that id."),
    "ERR_TOLERANCE_STANDARD_NOT_FOUND": (404, "No tolerance standard with that id."),
    "ERR_LENS_BLANK_LOT_NOT_FOUND": (404, "No blank lot with that id."),
    "ERR_LAB_MACHINE_NOT_FOUND": (404, "No lab machine with that id."),
    "ERR_FINISHING_BAY_NOT_FOUND": (404, "No finishing bay with that id."),
    "ERR_PRESCRIPTION_NOT_FOUND": (404, "No prescription with that id."),
    "ERR_RX_ORDER_NOT_FOUND": (404, "No order with that id."),
    "ERR_FRAME_LAYOUT_NOT_FOUND": (404, "No frame layout with that id."),
    "ERR_LAB_JOB_NOT_FOUND": (404, "No lab job with that id."),
    "ERR_LAB_OPERATION_NOT_FOUND": (404, "No lab operation with that id."),
    "ERR_QUALITY_INSPECTION_NOT_FOUND": (404, "No quality inspection with that id."),
    "ERR_REMAKE_CASE_NOT_FOUND": (404, "No remake case with that id."),
    # uniqueness
    "ERR_DUPLICATE_NPI": (409, "Another prescriber already holds that NPI."),
    "ERR_DUPLICATE_PLAN_CODE": (409, "Another insurance plan already holds that plan code."),
    "ERR_DUPLICATE_DESIGN_CODE": (409, "Another lens design already holds that design code."),
    "ERR_ACTIVE_LAB_JOB_EXISTS": (409, "The order already has an active lab job."),
    "ERR_EYE_ALREADY_INSPECTED_THIS_CYCLE": (409, "That eye has already been inspected at the job's current rework cycle."),
    "ERR_OPEN_REMAKE_CASE_EXISTS": (409, "The job already has an open remake case."),
    # prescription intake and verification
    "ERR_MEMBER_NUMBER_REQUIRED": (400, "A patient attached to an insurance plan must carry a member number."),
    "ERR_RX_POWER_OUT_OF_RANGE": (400, "A prescription power value is outside the dispensable range or is not a multiple of 0.25 diopters."),
    "ERR_RX_AXIS_REQUIRED": (400, "An axis is required whenever the cylinder for that eye is non-zero."),
    "ERR_RX_ISSUE_DATE_IN_FUTURE": (400, "A prescription cannot be issued in the future."),
    "ERR_PD_OUT_OF_RANGE": (400, "The pupillary distance is outside the measurable range."),
    "ERR_RX_STATE_INVALID": (409, "The prescription's verification state does not permit that action."),
    "ERR_NOT_PRESCRIBER_OF_RECORD": (403, "Only the prescriber of record may attest to this prescription."),
    "ERR_PRESCRIBER_NOT_ACTIVE": (422, "The prescriber is not in active standing."),
    "ERR_PRESCRIBER_RECORD_MISMATCH": (422, "The NPI or licensing state on the prescription does not match the prescriber record."),
    # order intake
    "ERR_RX_PATIENT_MISMATCH": (422, "The prescription belongs to a different patient."),
    "ERR_COATING_NOT_AVAILABLE_FOR_DESIGN": (422, "A requested coating is not offered on that lens design."),
    "ERR_DESIGN_INCOMPATIBLE_WITH_RX": (422, "A multifocal prescription cannot be filled with a single vision design."),
    "ERR_RX_NOT_VERIFIED": (409, "The prescription has not been verified."),
    "ERR_RX_EXPIRED": (422, "The prescription has expired."),
    "ERR_MONOCULAR_PD_INCONSISTENT": (422, "The monocular pupillary distances do not sum to the prescribed binocular PD within tolerance."),
    "ERR_PRIOR_AUTH_REQUIRED": (422, "The plan requires a prior authorization reference for specialty designs."),
    # layout
    "ERR_ORDER_STATE_INVALID": (409, "The order's fulfillment state does not permit that action."),
    "ERR_STALE_RX_ORDER_VERSION": (412, "The order has been modified since it was read; re-read it and retry."),
    "ERR_TRACE_DIMENSIONS_OUT_OF_RANGE": (400, "A frame trace dimension is outside the traceable range, or the effective diameter is smaller than the A dimension."),
    "ERR_FITTING_HEIGHT_BELOW_DESIGN_MINIMUM": (422, "The effective fitting height is below the lens design's minimum."),
    "ERR_LAYOUT_NOT_USABLE": (422, "The order has no current layout that can be sent to the lab."),
    # lab job and operations
    "ERR_NO_ELIGIBLE_BLANK_LOT": (409, "No available blank lot is large enough for the computed layout."),
    "ERR_STALE_LAB_JOB_VERSION": (412, "The lab job has been modified since it was read; re-read it and retry."),
    "ERR_OPERATION_WINDOW_INVALID": (400, "The operation window is empty, inverted, or longer than eight hours."),
    "ERR_RESOURCE_TYPE_MISMATCH": (400, "Surfacing requires a generator machine and edging requires a finishing bay; exactly one resource may be supplied."),
    "ERR_OPERATION_NOT_PERMITTED_FOR_ROUTE": (422, "A stock edge-only job has no surfacing step."),
    "ERR_MACHINE_NOT_AVAILABLE": (409, "The machine is on calibration hold or down."),
    "ERR_MACHINE_WINDOW_CONFLICT": (409, "The machine is already occupied in that window, allowing for its calibration buffer."),
    "ERR_BAY_NOT_OPEN": (409, "The finishing bay is closed."),
    "ERR_BAY_CAPACITY_EXCEEDED": (409, "The finishing bay is already at its concurrent capacity for that window."),
    "ERR_OPERATION_STATE_INVALID": (409, "The operation's state does not permit that action."),
    "ERR_LAB_JOB_STATE_INVALID": (409, "The lab job's state does not permit that action."),
    "ERR_BREAKAGE_NOT_APPLICABLE": (422, "Breakage can only be reported against a surfacing operation."),
    # inspection
    "ERR_UNKNOWN_DEFECT_CODE": (400, "An unrecognised defect code was supplied."),
    "ERR_NO_TOLERANCE_STANDARD": (422, "No tolerance standard is in effect for that design type and power band."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The acting user already performed a conflicting step on this work."),
    # billing
    "ERR_BILLING_STATE_INVALID": (409, "The order's billing state does not permit that action."),
    "ERR_ROUTE_NOT_DETERMINED": (409, "The final quote cannot be produced before the lab route is known."),
    "ERR_BENEFIT_CAP_EXHAUSTED": (422, "The patient's annual benefit cap is already fully consumed."),
    "ERR_SETTLEMENT_AMOUNT_INVALID": (400, "The payment amount must be positive and no larger than the outstanding balance."),
    "ERR_BALANCE_OUTSTANDING": (409, "The patient balance must be zero before dispensing."),
    "ERR_BILLING_ALREADY_FINALIZED": (409, "An order whose billing has been finalized cannot be cancelled without charge."),
    "ERR_OPERATION_IN_PROGRESS": (409, "An operation is currently running on the order's lab job."),
    # remake
    "ERR_REMAKE_LIMIT_REACHED": (422, "The order has already used its two permitted remakes."),
    "ERR_INSPECTION_JOB_MISMATCH": (422, "The referenced inspection belongs to a different lab job."),
    "ERR_REMAKE_STATE_INVALID": (409, "The remake case's state does not permit that action."),
    "ERR_INSPECTION_REQUIRED_FOR_METHOD": (422, "Tolerance-delta adjudication needs a linked quality inspection."),
    "ERR_REMAKE_NOT_DELIVERABLE": (409, "A remake case cannot be closed before the replacement eyewear has been produced."),
    # fallback for unmatched routes
    "ERR_NOT_FOUND": (404, "No such resource."),
    "ERR_METHOD_NOT_ALLOWED": (405, "Method not allowed for this path."),
}
