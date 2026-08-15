"""Error types and the error catalog (error_id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error ID constants (from the PRD error catalogue)
ERR_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"          # 400
ERR_FORBIDDEN = "ERR_INSUFFICIENT_PERMISSIONS"                   # 403
ERR_NOT_OWNER = "ERR_NOT_RESOURCE_OWNER"                         # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                  # 404
ERR_INVALID = "ERR_INVALID_REQUEST"                              # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"                          # 412
ERR_PROPOSAL_STATE = "ERR_PROPOSAL_INVALID_STATE"                # 409
ERR_COMMITMENT_STATE = "ERR_COMMITMENT_INVALID_STATE"            # 409
ERR_REVIEW_STATE = "ERR_REVIEW_INVALID_STATE"                    # 409
ERR_OFFER_STATE = "ERR_OFFER_INVALID_STATE"                      # 409
ERR_HANDOFF_STATE = "ERR_HANDOFF_INVALID_STATE"                  # 409
ERR_RATE_AGREEMENT_STATE = "ERR_RATE_AGREEMENT_INVALID_STATE"    # 409
ERR_SELF_APPROVAL = "ERR_SELF_APPROVAL"                          # 403
ERR_COST_SHARE_SELF_APPROVAL = "ERR_COST_SHARE_SELF_APPROVAL"    # 403
ERR_PI_NOT_ELIGIBLE = "ERR_PI_NOT_ELIGIBLE"                      # 403
ERR_OPPORTUNITY_CLOSED = "ERR_OPPORTUNITY_CLOSED"                # 409
ERR_DEADLINE_PASSED = "ERR_INTERNAL_DEADLINE_PASSED"             # 422
ERR_COMPLIANCE_DISAPPROVED = "ERR_COMPLIANCE_DISAPPROVED"        # 409
ERR_COMPLIANCE_EXPIRED = "ERR_COMPLIANCE_APPROVAL_EXPIRED"       # 409
ERR_COMPLIANCE_PENDING = "ERR_COMPLIANCE_REVIEW_PENDING"         # 409
ERR_COI_INCOMPLETE = "ERR_COI_DISCLOSURE_INCOMPLETE"             # 422
ERR_ACTIVITY_NOT_ALLOWED = "ERR_ACTIVITY_CODE_NOT_ALLOWED"       # 422
ERR_PI_LIMIT = "ERR_PI_PROPOSAL_LIMIT_EXCEEDED"                  # 409
ERR_DUPLICATE_REVIEW = "ERR_DUPLICATE_ACTIVE_REVIEW"             # 409
ERR_RATE_OVERLAP = "ERR_FA_RATE_WINDOW_OVERLAP"                  # 409
ERR_PI_EFFORT = "ERR_PI_EFFORT_EXCEEDED"                         # 422
ERR_EMPTY_BUDGET = "ERR_EMPTY_BUDGET"                            # 422
ERR_NO_RATE = "ERR_NO_APPLICABLE_RATE"                           # 422
ERR_RATE_NOT_FINAL = "ERR_RATE_NOT_FINAL"                        # 409
ERR_STALE_SNAPSHOT = "ERR_STALE_BUDGET_SNAPSHOT"                 # 409
ERR_SUBREC_DOCS = "ERR_SUBREC_DOCS_INCOMPLETE"                   # 422
ERR_SUBREC_HIGH_RISK = "ERR_SUBREC_HIGH_RISK_NOT_ACKED"          # 422
ERR_SUBREC_NOT_VERIFIED = "ERR_SUBRECIPIENT_NOT_VERIFIED"        # 409
ERR_UEI_NOT_UNIQUE = "ERR_UEI_NOT_UNIQUE"                        # 409
ERR_REQUEST_CAP = "ERR_REQUEST_EXCEEDS_CAP"                      # 422
ERR_COST_SHARE_INADEQUATE = "ERR_COST_SHARE_INADEQUATE"          # 422


def bad_request(msg):
    return ApiError(ERR_INVALID, 400, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)
