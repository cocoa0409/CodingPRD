"""Error classes and the complete error catalog (PRD §5, SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> (http_status, default message)
CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Missing or unknown authentication headers."),
    "ERR_FORBIDDEN_ROLE": (403, "Role is not permitted for this operation."),
    "ERR_NOT_OWNER": (403, "Acting principal does not own this resource."),
    "ERR_NOT_FOUND": (404, "Resource not found."),
    "ERR_INVALID_STATE": (409, "Resource is not in a state that admits this transition."),
    "ERR_TRUST_IRREVOCABLE": (409, "An irrevocable trust may not be amended or revoked."),
    "ERR_SEGREGATION_OF_DUTIES": (409, "The approver may not be the proposer."),
    "ERR_ACCOUNT_PERIOD_OVERLAP": (409, "Accounting period overlaps an existing period."),
    "ERR_TRUSTEE_TERM_CONFLICT": (409, "Trustee term conflicts with an existing appointment."),
    "ERR_PERIOD_FROZEN": (409, "The accounting period is frozen."),
    "ERR_INVALID_AMOUNT": (422, "Amount or generation level is invalid."),
    "ERR_GRANTOR_MISMATCH": (409, "Beneficiary/grantor is inconsistent with the trust."),
    "ERR_INSUFFICIENT_CORPUS": (409, "Insufficient corpus to pay the distribution."),
    "ERR_GST_EXEMPTION_EXCEEDED": (409, "Allocation exceeds the grantor's remaining exemption."),
    "ERR_STALE_TRUST_VERSION": (412, "Trust version is stale."),
    "ERR_ALLOCATION_CONSUMED": (409, "The allocation has already been consumed by a GST event."),
    "ERR_UNSETTLED_DISTRIBUTION": (409, "An unsettled distribution blocks termination."),
    "ERR_VALIDATION": (422, "Malformed request body."),
}


def err(error_id, message=None):
    http_status = CATALOG[error_id][0]
    if message is None:
        message = CATALOG[error_id][1]
    return ApiError(error_id, http_status, message)
