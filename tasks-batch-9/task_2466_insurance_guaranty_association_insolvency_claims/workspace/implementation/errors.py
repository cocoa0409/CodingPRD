"""Error catalogue for the Insurance Guaranty Association API.

Every error identifier and its HTTP status is taken verbatim from PRD section 5
and SCAFFOLD.yaml `errors`.
"""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_ASSIGNED_ADJUSTER": 403,
    "ERR_NOT_ASSESSED_MEMBER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INSOLVENCY_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_MEMBER_ASSESSMENT_NOT_FOUND": 404,
    "ERR_MEMBER_INSURER_NOT_FOUND": 404,
    "ERR_CHILD_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCED_ROW_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_STALE_INSOLVENCY_VERSION": 412,
    "ERR_CLAIM_INVALID_STATE": 409,
    "ERR_REMAND_LIMIT_REACHED": 409,
    "ERR_TRANSFER_INVALID_STATE": 409,
    "ERR_ASSESSMENT_INVALID_STATE": 409,
    "ERR_MEMBER_ASSESSMENT_INVALID_STATE": 409,
    "ERR_REFERRAL_ALREADY_ANSWERED": 409,
    "ERR_INSOLVENCY_NOT_TRIGGERED": 409,
    "ERR_INSOLVENCY_CLOSED": 409,
    "ERR_INSOLVENCY_ALREADY_TRIGGERED": 409,
    "ERR_POLICY_NOT_CANCELLED": 409,
    "ERR_FILING_DEADLINE_PASSED": 422,
    "ERR_NET_WORTH_EXCLUSION": 422,
    "ERR_COVERAGE_PROFILE_MISSING": 422,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_UP_REFUND_ALREADY_FILED": 409,
    "ERR_MEMBER_DUPLICATE_LINE": 409,
    "ERR_POLICY_PERIOD_OVERLAP": 409,
    "ERR_ADJUSTER_ENGAGEMENT_OVERLAP": 409,
    "ERR_REFERRAL_BASIS_MISMATCH": 422,
    "ERR_REFERRAL_ALREADY_OPEN": 409,
    "ERR_SURCHARGE_AGGREGATE_EXCEEDED": 422,
    "ERR_OTHER_INSURANCE_NOT_EXHAUSTED": 409,
    "ERR_RECOUPMENT_NOT_FILED": 409,
    "ERR_CLAIMS_OUTSTANDING": 409,
    "ERR_REFUNDS_OUTSTANDING": 409,
    "ERR_ADJUSTER_AUTHORITY_EXCEEDED": 422,
    "ERR_OVERPAYMENT": 422,
    "ERR_AGGREGATE_CAP_EXHAUSTED": 422,
    "ERR_OVER_RECOUPMENT": 422,
    "ERR_PREMIUM_BASE_EMPTY": 422,
    "ERR_INSUFFICIENT_ESTATE_FUNDS": 422,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with an envelope error."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_CATALOG.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)
