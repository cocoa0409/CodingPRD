"""Error catalogue (PRD section 5 / SCAFFOLD 1.6) and the ApiError exception."""

# error_id -> (http_status, default message)
ERROR_CATALOG = {
    # --- authentication / authorization ---
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are missing or the identity cannot be resolved."),
    "ERR_UNAUTHORIZED": (403, "The acting role may not perform this operation."),
    "ERR_NOT_ENGAGEMENT_LEAD": (403, "Only the engagement's lead assessor may perform this operation."),
    "ERR_NOT_ENGAGEMENT_QA_REVIEWER": (403, "Only the engagement's assigned QA reviewer may perform this operation."),
    "ERR_VENDOR_SCOPE_FORBIDDEN": (403, "The acting scanning vendor does not own this scan cycle."),

    # --- request shape ---
    "ERR_INVALID_REQUEST": (400, "The request body or query string is malformed."),

    # --- existence ---
    "ERR_ASSESSOR_NOT_FOUND": (404, "Assessor not found."),
    "ERR_ASV_VENDOR_NOT_FOUND": (404, "Approved scanning vendor not found."),
    "ERR_ENGAGEMENT_NOT_FOUND": (404, "Engagement not found."),
    "ERR_SEGMENT_NOT_FOUND": (404, "Network segment not found."),
    "ERR_COMPONENT_NOT_FOUND": (404, "System component not found."),
    "ERR_SAMPLING_PLAN_NOT_FOUND": (404, "Sampling plan not found."),
    "ERR_REQUIREMENT_NOT_FOUND": (404, "Requirement assessment not found."),
    "ERR_EVIDENCE_NOT_FOUND": (404, "Evidence item not found."),
    "ERR_CCW_NOT_FOUND": (404, "Compensating control worksheet not found."),
    "ERR_REMEDIATION_ITEM_NOT_FOUND": (404, "Remediation item not found."),
    "ERR_ROC_NOT_FOUND": (404, "Report on compliance not found."),
    "ERR_SCAN_CYCLE_NOT_FOUND": (404, "Scan cycle not found."),
    "ERR_SCAN_FINDING_NOT_FOUND": (404, "Scan finding not found."),
    "ERR_CHANGE_LOG_ENTRY_NOT_FOUND": (404, "Change log entry not found."),

    # --- posture gates ---
    "ERR_ENGAGEMENT_FROZEN": (409, "The engagement posture is FROZEN and rejects this write."),
    "ERR_ENGAGEMENT_RESTRICTED": (409, "The engagement posture is RESTRICTED and rejects this write."),

    # --- target state ---
    "ERR_INVALID_ENGAGEMENT_STATE": (409, "The engagement is not in a state that admits this transition."),
    "ERR_INVALID_SEGMENT_STATE": (409, "The network segment is not in a state that admits this transition."),
    "ERR_INVALID_REQUIREMENT_STATE": (409, "The requirement assessment is not in a state that admits this transition."),
    "ERR_INVALID_CCW_STATE": (409, "The worksheet is not in a state that admits this transition."),
    "ERR_INVALID_REMEDIATION_STATE": (409, "The remediation item is not in a state that admits this transition."),
    "ERR_INVALID_ROC_STATE": (409, "The report is not in a state that admits this transition."),
    "ERR_INVALID_SCAN_CYCLE_STATE": (409, "The scan cycle is not in a state that admits this transition."),
    "ERR_INVALID_FINDING_DISPUTE_STATE": (409, "The finding's dispute status does not admit this transition."),

    # --- optimistic concurrency ---
    "ERR_STALE_ENGAGEMENT_VERSION": (412, "The supplied engagement version does not match the stored version."),
    "ERR_STALE_REQUIREMENT_VERSION": (412, "The supplied requirement version does not match the stored version."),

    # --- referential coherence ---
    "ERR_CROSS_ENGAGEMENT_REFERENCE": (422, "The referenced row belongs to a different engagement."),
    "ERR_SEGMENT_CYCLE": (422, "The proposed parent would create a cycle in the segment forest."),
    "ERR_ASV_NOT_APPROVED": (422, "The scanning vendor's approval is not effective."),

    # --- segregation of duties / independence ---
    "ERR_INDEPENDENCE_VIOLATION": (422, "The acting reviewer is not independent of the work under review."),
    "ERR_SEGREGATION_OF_DUTIES": (422, "The QA reviewer may not be the lead assessor."),
    "ERR_QA_NOT_QUALIFIED": (422, "The nominated QA reviewer is not QA qualified."),
    "ERR_ASSESSOR_NOT_ACTIVE": (422, "The referenced assessor is not ACTIVE."),

    # --- temporal ---
    "ERR_ASSESSOR_CERTIFICATION_EXPIRED": (422, "The assessor's certification has lapsed."),
    "ERR_ASSESSOR_WINDOW_CONFLICT": (422, "The lead assessor already has an overlapping fieldwork window."),
    "ERR_SCAN_WINDOW_OVERLAP": (422, "The scan window overlaps an existing cycle for this engagement."),
    "ERR_NO_PASSING_SCAN": (422, "The engagement has no passing scan covering the current instant."),

    # --- business constraints ---
    "ERR_DUPLICATE_ASSESSOR_EMAIL": (422, "An assessor with that email already exists."),
    "ERR_DUPLICATE_VENDOR_NAME": (422, "A scanning vendor with that name already exists."),
    "ERR_DUPLICATE_SEGMENT_NAME": (422, "A segment with that name already exists on this engagement."),
    "ERR_DUPLICATE_HOSTNAME": (422, "A component with that hostname already exists on this engagement."),
    "ERR_DUPLICATE_REQUIREMENT_REF": (422, "That requirement reference already exists on this engagement."),
    "ERR_DUPLICATE_QUARTER_LABEL": (422, "That quarter label already exists on this engagement."),
    "ERR_FACILITY_TYPE_CONFLICT": (422, "The facility name is already recorded with a different facility type."),
    "ERR_EMPTY_SAMPLE_POPULATION": (422, "The engagement has no eligible components to sample."),
    "ERR_SAMPLING_PLAN_STALE": (422, "The engagement's latest sampling plan is not an ACTIVE FINAL plan."),
    "ERR_NO_CDE_SEGMENT": (422, "The engagement has no validated CDE segment."),
    "ERR_SEGMENT_HAS_COMPONENTS": (422, "The segment still has components or child segments attached."),
    "ERR_COMPONENT_NOT_IN_SAMPLE": (422, "The referenced component is not in the sample."),
    "ERR_EVIDENCE_TARGET_REQUIRED": (422, "This evidence type requires a component reference."),
    "ERR_INTERVIEWEE_REQUIRED": (422, "Interview evidence requires an interviewee name and title."),
    "ERR_EVIDENCE_INCOMPLETE": (422, "The requirement's evidence is not complete."),
    "ERR_CCW_SECTION_INCOMPLETE": (422, "The worksheet has an empty mandatory section."),
    "ERR_CCW_MONITORING_INTERVAL_TOO_LONG": (422, "The monitoring interval exceeds the acceptance ceiling."),
    "ERR_CCW_RIGOR_INSUFFICIENT": (422, "The worksheet's rigor score is below the acceptance floor."),
    "ERR_REQUIREMENT_TESTING_INCOMPLETE": (422, "At least one requirement is still untested."),
    "ERR_NO_APPLICABLE_REQUIREMENTS": (422, "The engagement has no applicable requirements."),
    "ERR_ROC_ALREADY_EXISTS": (422, "The engagement already has a report on compliance."),
    "ERR_QA_REVIEWER_NOT_ASSIGNED": (422, "The engagement has no QA reviewer assigned."),
    "ERR_ATTESTATION_SIGNATURE_MISMATCH": (422, "The attestation signature does not match the lead assessor's name."),
    "ERR_FINDING_NOT_HIGH_SEVERITY": (422, "Only HIGH_OR_ABOVE findings may be disputed."),
    "ERR_INVALID_REASSESSMENT_YEAR": (422, "The reassessment target year or planned start date is invalid."),

    # --- fiscal ---
    "ERR_ASSESSMENT_BUDGET_EXCEEDED": (422, "The recomputed assessment fee exceeds the approved budget."),
}


class ApiError(Exception):
    """Raised anywhere in the request path; converted to the error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        status, default_message = ERROR_CATALOG.get(error_id, (400, error_id))
        self.http_status = http_status if http_status is not None else status
        self.message = message if message is not None else default_message
