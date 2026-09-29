"""Error catalog and API exception type."""

# error_id -> (http_status, default message)
CATALOG = {
    # envelope / auth
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are missing or invalid."),
    "ERR_UNAUTHORIZED": (403, "This role may not perform the requested operation."),
    "ERR_NOT_RESOURCE_OWNER": (403, "The addressed resource belongs to another distributor."),
    "ERR_INVALID_REQUEST": (400, "The request body or query is malformed."),
    "ERR_CLAIM_DATES_INVALID": (400, "reported_on may not precede installed_on."),
    # not found
    "ERR_DISTRIBUTOR_NOT_FOUND": (404, "Distributor not found."),
    "ERR_RAW_MATERIAL_NOT_FOUND": (404, "Raw material not found."),
    "ERR_FORMULATION_NOT_FOUND": (404, "Formulation not found."),
    "ERR_FORMULATION_COMPONENT_NOT_FOUND": (404, "Formulation component not found on this recipe."),
    "ERR_DESIGN_LICENSE_NOT_FOUND": (404, "Design license not found."),
    "ERR_PRINT_FILM_NOT_FOUND": (404, "Print film not found."),
    "ERR_PRODUCT_SKU_NOT_FOUND": (404, "Product SKU not found."),
    "ERR_PRESS_LINE_NOT_FOUND": (404, "Press line not found."),
    "ERR_TEST_PANEL_NOT_FOUND": (404, "Test panel not found."),
    "ERR_PRODUCTION_RUN_NOT_FOUND": (404, "Production run not found."),
    "ERR_BATCH_NOT_FOUND": (404, "Batch not found."),
    "ERR_ALLOCATION_NOT_FOUND": (404, "Allocation not found."),
    "ERR_WARRANTY_CLAIM_NOT_FOUND": (404, "Warranty claim not found."),
    # own-entity state
    "ERR_INVALID_FORMULATION_STATE": (409, "The formulation is not in a state that allows this operation."),
    "ERR_INVALID_LICENSE_STATE": (409, "The design license is not in a state that allows this operation."),
    "ERR_INVALID_SKU_CERTIFICATION_STATE": (409, "The SKU certification state does not allow this operation."),
    "ERR_INVALID_COMMERCIAL_STATE": (409, "The SKU commercial state does not allow this transition."),
    "ERR_INVALID_PANEL_STATE": (409, "The test panel is not in a state that allows this operation."),
    "ERR_INVALID_RUN_STATE": (409, "The production run is not in a state that allows this operation."),
    "ERR_INVALID_QC_TRANSITION": (409, "The requested QC disposition is not reachable from the current one."),
    "ERR_INVALID_BATCH_STATE": (409, "The batch is not in a state that allows this operation."),
    "ERR_INVALID_PRINT_FILM_STATE": (409, "The print film is not in a state that allows this operation."),
    "ERR_INVALID_ALLOCATION_STATE": (409, "The allocation is not in a state that allows this operation."),
    "ERR_INVALID_CLAIM_STATE": (409, "The warranty claim is not in a state that allows this operation."),
    # concurrency
    "ERR_STALE_FORMULATION_VERSION": (412, "The formulation has changed since it was read; re-read and retry."),
    "ERR_STALE_ALLOCATION_VERSION": (412, "The allocation has changed since it was read; re-read and retry."),
    # segregation of duties
    "ERR_SEGREGATION_OF_DUTIES": (403, "The acting user already performed the conflicting step of this workflow."),
    # cross-entity state
    "ERR_SKU_NOT_PRODUCIBLE": (409, "The SKU is not in a certification or commercial state that allows this operation."),
    "ERR_PRESS_LINE_UNAVAILABLE": (409, "The press line is not available."),
    "ERR_RUN_NOT_RELEASED": (409, "The producing run has not been released by QC."),
    # business safety
    "ERR_SLIP_RESISTANCE_NOT_QUALIFIED": (422, "A waterproof-rated SKU may not run without a passing slip-resistance result."),
    "ERR_QC_GATES_NOT_MET": (422, "One or more QC gates failed; the run cannot be released."),
    "ERR_TEST_COVERAGE_INCOMPLETE": (422, "Required test coverage for this SKU configuration is incomplete."),
    # business constraint
    "ERR_PERFORMANCE_SCORE_BELOW_MINIMUM": (422, "The blend performance score is below the approval minimum of 60.00."),
    "ERR_INDENTATION_CLASS_TOO_LOW": (422, "The blend indentation resistance class is too low for approval."),
    "ERR_RESIN_PHR_NOT_NORMALIZED": (422, "A recipe must dose exactly 100.00 phr of vinyl resin before review."),
    "ERR_PHR_EXCEEDS_MATERIAL_MAX": (422, "The requested dosage exceeds the material's maximum phr."),
    "ERR_DUPLICATE_CODE": (409, "That code is already in use."),
    "ERR_THICKNESS_OUT_OF_LINE_RANGE": (422, "The SKU thickness is outside the press line's forming range."),
    "ERR_TOLERANCE_BAND_INVALID": (422, "The click-lock milling tolerance band is invalid."),
    "ERR_RETEST_LIMIT_EXCEEDED": (422, "The panel has exhausted its permitted retests."),
    "ERR_ALLOCATION_OVER_REQUEST": (422, "The allocation has already drawn its full requested quantity."),
    # business temporal
    "ERR_PRESS_LINE_WINDOW_CONFLICT": (409, "The requested window overlaps an existing run on this press line."),
    "ERR_CHANGEOVER_GAP_INSUFFICIENT": (409, "The gap from the preceding run is shorter than the required changeover."),
    "ERR_PRINT_FILM_ROLL_CAPACITY_EXCEEDED": (409, "No master roll set of this print film is free for the requested window."),
    "ERR_LICENSE_EXPIRED": (409, "The governing design license is outside its licensed term."),
    "ERR_SETUP_TOO_EARLY": (409, "Setup may not begin more than 120 minutes before the planned start."),
    "ERR_WARRANTY_EXPIRED": (409, "The warranty term for this batch has been exhausted."),
    # business referential
    "ERR_FORMULATION_NOT_APPROVED": (409, "The SKU's formulation is not approved."),
    "ERR_RAW_MATERIAL_NOT_ACTIVE": (409, "A raw material in this recipe is no longer active."),
    "ERR_PRINT_FILM_NOT_AVAILABLE": (409, "The SKU's print film is not available."),
    "ERR_LICENSE_NOT_ACTIVE": (409, "The governing design license is not active."),
    "ERR_BATCH_NOT_TRACEABLE": (409, "The batch has no traceability evidence for a warranty claim."),
    "ERR_NO_ELIGIBLE_BATCH": (409, "No eligible batch satisfies this allocation's substitution policy."),
    "ERR_REVIEW_OUTCOME_CONFLICT": (409, "Not every required review confirmed the defect."),
    # business fiscal
    "ERR_LICENSE_VOLUME_CAP_EXCEEDED": (422, "The licensed term volume cap would be exceeded."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        status, default_message = CATALOG.get(error_id, (400, "The request could not be processed."))
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else status
        self.message = message if message is not None else default_message
        super().__init__(self.message)


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
