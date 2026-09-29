"""Error catalogue (PRD section 5) and the ApiError exception."""

# error_id -> (http_status, default message)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "X-User-ID and X-User-Role headers are required and the role must be one of the six declared roles."),
    "ERR_FORBIDDEN_ROLE": (403, "The caller's role is not authorised for this endpoint."),
    "ERR_NOT_RESOURCE_OWNER": (403, "An Applicant may only act on their own records."),

    "ERR_BOARD_CONFIG_NOT_FOUND": (404, "No StateBoardConfig exists for the supplied id."),
    "ERR_PROGRAM_NOT_FOUND": (404, "No EducationProgram exists for the supplied id."),
    "ERR_NURSE_NOT_FOUND": (404, "No Nurse exists for the supplied id."),
    "ERR_APPLICATION_NOT_FOUND": (404, "No LicenseApplication exists for the supplied id."),
    "ERR_LICENSE_NOT_FOUND": (404, "No License exists for the supplied id."),
    "ERR_RENEWAL_NOT_FOUND": (404, "No RenewalApplication exists for the supplied id."),
    "ERR_CE_RECORD_NOT_FOUND": (404, "No CeRecord exists for the supplied id."),
    "ERR_COMPLAINT_NOT_FOUND": (404, "No Complaint exists for the supplied id."),
    "ERR_EVIDENCE_REQUEST_NOT_FOUND": (404, "No EvidenceRequest exists for the supplied id."),
    "ERR_MONITORING_AGREEMENT_NOT_FOUND": (404, "No MonitoringAgreement exists for the supplied id."),
    "ERR_PROCEEDING_NOT_FOUND": (404, "No DisciplinaryProceeding exists for the supplied id."),
    "ERR_NOTIFICATION_REPORT_NOT_FOUND": (404, "No NotificationReport exists for the supplied id."),

    "ERR_INVALID_REQUEST": (400, "The request body is not well formed."),
    "ERR_INVALID_PAGINATION": (400, "limit must be an integer in 1..100 and offset an integer >= 0."),

    "ERR_STATE_CODE_EXISTS": (409, "A StateBoardConfig already exists with the supplied state_code."),
    "ERR_PROGRAM_CODE_EXISTS": (409, "An EducationProgram already exists with the supplied program_code for this board."),
    "ERR_STALE_VERSION": (412, "The supplied expected version does not match the parent's current version."),

    "ERR_INVALID_STATE": (409, "The resource is not in a valid state for the requested transition."),
    "ERR_LICENSE_NOT_RENEWABLE": (409, "The credential is not renewable."),
    "ERR_LICENSE_ENCUMBERED": (409, "The credential is disciplinarily barred from renewal."),
    "ERR_LICENSE_ALREADY_ISSUED": (409, "A live credential of this type already exists for this nurse at this board."),

    "ERR_PHI_AUTHORIZATION_REQUIRED": (422, "A protected-health-information records demand requires phi_authorization_id."),
    "ERR_PRESIDING_MEMBER_CANNOT_VOTE": (403, "The presiding member may not cast a panel vote."),
    "ERR_VOTER_CONFLICT_OF_INTEREST": (403, "The caller is not a seated, non-conflicted panel member."),
    "ERR_DISQUALIFYING_OFFENSE": (422, "APPROVED_UNCONDITIONAL may not be recorded on a disqualifying screening."),

    "ERR_CUSTODIAN_NOT_LINKED": (422, "The custodian_code is not linked to the complaint."),

    "ERR_NOTICE_PERIOD_NOT_MET": (422, "hearing_date does not honour the notice period."),
    "ERR_MONITORING_PERIOD_CONFLICT": (409, "The proposed monitoring period conflicts with an existing agreement."),
    "ERR_CUSTODIAN_HOLD_CAPACITY": (409, "The custodian is already at its concurrent-hold ceiling."),

    "ERR_PROGRAM_NOT_APPROVED": (422, "The referenced education program is not in an acceptable approval posture."),
    "ERR_NCLEX_NOT_PASSED": (422, "The examination result is not PASS."),
    "ERR_PRIOR_LICENSE_UNVERIFIED": (422, "The prior license has not been verified."),
    "ERR_BASE_LICENSE_REQUIRED": (422, "A qualifying base credential is required for an APRN application."),
    "ERR_DEFICIENCY_LIMIT_REACHED": (409, "The deficiency budget for this application is exhausted."),
    "ERR_CONSOLIDATION_TARGET_INVALID": (409, "The consolidation target is invalid."),
    "ERR_ATD_INELIGIBLE": (422, "The complaint or nurse is not eligible for alternative-to-discipline monitoring."),
    "ERR_QUORUM_NOT_MET": (422, "Fewer than three seated, non-recused members remain."),
    "ERR_CONTINUANCE_LIMIT_REACHED": (409, "The continuance budget for this proceeding is exhausted."),
    "ERR_AUDIT_DOC_REQUEST_LIMIT_REACHED": (409, "The audit documentation-request budget is exhausted."),
    "ERR_AUDIT_DOCS_NOT_SUBMITTED": (409, "No submitted practice-hour documentation to decide on."),
    "ERR_SANCTION_BELOW_FLOOR": (422, "The adopted sanction is below the frozen sanction floor."),

    "ERR_CE_HOURS_INSUFFICIENT": (422, "The provisional continuing-education total is below the board's requirement."),
    "ERR_RENEWAL_FEE_UNPAID": (402, "The renewal fee has not been assessed or is underpaid."),
    "ERR_PRACTICE_HOURS_INSUFFICIENT": (422, "The renewal stands on a failed practice-hour audit."),

    "ERR_NOT_FOUND": (404, "The requested resource does not exist."),
    "ERR_METHOD_NOT_ALLOWED": (405, "The HTTP method is not allowed for this path."),
    "ERR_INTERNAL": (500, "Internal server error."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        status, default_message = ERROR_CATALOG.get(error_id, (400, error_id))
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else status
        self.message = message or default_message


def fail(error_id, message=None):
    raise ApiError(error_id, message)
