"""Error catalogue for the DR Failover Exercise API.

Every error_id / HTTP status pair below is taken verbatim from PRD.md section 5
(Error Code Catalogue) and the SCAFFOLD.yaml `errors` table.
"""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ROLE_IDENTITY_MISMATCH": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STAKEHOLDER_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_DEPENDENCY_EDGE_NOT_FOUND": 404,
    "ERR_RECOVERY_GROUP_NOT_FOUND": 404,
    "ERR_RUNBOOK_NOT_FOUND": 404,
    "ERR_RUNBOOK_STEP_NOT_FOUND": 404,
    "ERR_EXERCISE_NOT_FOUND": 404,
    "ERR_SCOPE_ITEM_NOT_FOUND": 404,
    "ERR_STEP_EXECUTION_NOT_FOUND": 404,
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_EVIDENCE_PACKAGE_NOT_FOUND": 404,
    "ERR_STALE_RECOVERY_GROUP_VERSION": 412,
    "ERR_STALE_EXERCISE_VERSION": 412,
    "ERR_INVALID_EXERCISE_STATE": 409,
    "ERR_INVALID_DATA_STATE": 409,
    "ERR_INVALID_FAILBACK_STATE": 409,
    "ERR_INVALID_RUNBOOK_STATE": 409,
    "ERR_INVALID_STEP_STATE": 409,
    "ERR_INVALID_APPLICATION_TIER_STATE": 409,
    "ERR_INVALID_FINDING_STATE": 409,
    "ERR_INVALID_EVIDENCE_STATE": 409,
    "ERR_EVIDENCE_SEALED": 409,
    "ERR_SOD_TIER_PROPOSER": 422,
    "ERR_SOD_IMPACT_APPROVER": 422,
    "ERR_SOD_STEP_OWNER": 422,
    "ERR_SOD_EVIDENCE_SIGNER": 422,
    "ERR_INSUFFICIENT_APPROVAL_AUTHORITY": 403,
    "ERR_RUNBOOK_STALE": 422,
    "ERR_GROUP_NOT_READY": 422,
    "ERR_GROUP_FROZEN": 422,
    "ERR_STEP_COVERS_UNAGREED_APPLICATION": 422,
    "ERR_GROUP_SITE_MISMATCH": 422,
    "ERR_SELF_DEPENDENCY": 422,
    "ERR_DEPENDENCY_CYCLE": 422,
    "ERR_DUPLICATE_DEPENDENCY_EDGE": 409,
    "ERR_DUPLICATE_SCOPE_ITEM": 409,
    "ERR_STEP_NOT_IN_SCOPE": 422,
    "ERR_RETEST_SCOPE_MISMATCH": 422,
    "ERR_TIER_RTO_EXCEEDS_CAP": 422,
    "ERR_TIER_RPO_EXCEEDS_CAP": 422,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_DUPLICATE_STEP_NUMBER": 409,
    "ERR_SITE_WINDOW_CONFLICT": 409,
    "ERR_GROUP_CHANGE_FREEZE_CONFLICT": 409,
    "ERR_RUNBOOK_VALIDITY_EXPIRED": 422,
    "ERR_EXERCISE_NOT_CLOSED": 422,
    "ERR_SITE_CAPACITY_EXCEEDED": 409,
    "ERR_NO_RTO_BASELINE": 422,
    "ERR_NO_REPLICATION_OBSERVATION": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_OBSERVATION_IN_FUTURE": 422,
    "ERR_NOT_APPLICATION_OWNER": 403,
    # generic fallback for unrouted paths
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with a catalogued error."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."


def bad_request(message="Request payload failed validation."):
    return ApiError("ERR_INVALID_REQUEST", message)
