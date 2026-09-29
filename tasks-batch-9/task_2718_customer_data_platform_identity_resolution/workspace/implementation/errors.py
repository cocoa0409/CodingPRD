"""Error catalog and API error exception for the CDP service."""

# error_id -> (http_status, default message)
ERROR_CATALOG = {
    "ERR_MISSING_AUTH_HEADERS": (401, "X-User-ID and X-User-Role headers are required."),
    "ERR_UNAUTHORIZED": (403, "The acting role may not perform this operation."),
    "ERR_DESTINATION_ACTOR_MISMATCH": (403, "The acting destination does not own this resource."),
    "ERR_INVALID_REQUEST": (400, "The request payload or query string is malformed."),
    "ERR_SOURCE_SYSTEM_NOT_FOUND": (404, "Source system not found."),
    "ERR_INGEST_BATCH_NOT_FOUND": (404, "Ingest batch not found."),
    "ERR_PROFILE_NOT_FOUND": (404, "Profile not found."),
    "ERR_HOUSEHOLD_NOT_FOUND": (404, "Household not found."),
    "ERR_MATCH_RULE_NOT_FOUND": (404, "Match rule not found."),
    "ERR_IDENTITY_LINK_NOT_FOUND": (404, "Identity link not found."),
    "ERR_CONSENT_RECORD_NOT_FOUND": (404, "Consent record not found."),
    "ERR_SUPPRESSION_ENTRY_NOT_FOUND": (404, "Suppression entry not found."),
    "ERR_SEGMENT_NOT_FOUND": (404, "Segment not found."),
    "ERR_DESTINATION_NOT_FOUND": (404, "Destination not found."),
    "ERR_ACTIVATION_NOT_FOUND": (404, "Activation not found."),
    "ERR_DELETION_REQUEST_NOT_FOUND": (404, "Deletion request not found."),
    "ERR_VENDOR_TASK_NOT_FOUND": (404, "Vendor deletion task not found."),
    "ERR_STALE_PROFILE_VERSION": (412, "The supplied profile version is stale."),
    "ERR_STALE_SEGMENT_VERSION": (412, "The supplied segment version is stale."),
    "ERR_STALE_DELETION_REQUEST_VERSION": (412, "The supplied deletion request version is stale."),
    "ERR_INVALID_STATE": (409, "The resource is not in a state that allows this transition."),
    "ERR_PROFILE_MERGED_AWAY": (409, "The profile has been merged away."),
    "ERR_SOURCE_SYSTEM_QUARANTINED": (409, "The source system is quarantined."),
    "ERR_MATCH_RULE_DISABLED": (409, "The match rule is disabled."),
    "ERR_DESTINATION_INACTIVE": (409, "The destination is inactive."),
    "ERR_PROFILE_DELETED": (409, "The profile has been deleted."),
    "ERR_LEGAL_HOLD_ACTIVE": (409, "A legal hold is active for this subject."),
    "ERR_SEGREGATION_OF_DUTIES": (409, "The submitter may not decide their own submission."),
    "ERR_GOVERNANCE_JUSTIFICATION_REQUIRED": (422, "A governance justification is required."),
    "ERR_GOVERNANCE_NOT_APPROVED": (409, "The segment has no live governance approval."),
    "ERR_SENSITIVE_ATTRIBUTE_NOT_PERMITTED": (409, "Sensitive attributes are not permitted here."),
    "ERR_EMPTY_AUDIENCE": (422, "The resolved audience is empty."),
    "ERR_AUDIENCE_BELOW_K_ANONYMITY": (422, "The resolved audience is below the k-anonymity floor."),
    "ERR_DUPLICATE_CODE": (409, "The code is already in use."),
    "ERR_DUPLICATE_EXTERNAL_ID": (422, "Duplicate external_id within the batch."),
    "ERR_INVALID_THRESHOLD_ORDER": (422, "auto_merge_threshold must be strictly greater than review_floor."),
    "ERR_DETERMINISTIC_KEY_MISMATCH": (422, "deterministic_key does not agree with rule_kind."),
    "ERR_SELF_LINK_FORBIDDEN": (422, "A profile may not be linked to itself."),
    "ERR_DUPLICATE_IDENTITY_LINK": (409, "An open identity link already exists for this pair."),
    "ERR_CONFIDENCE_BELOW_FLOOR": (422, "The computed confidence is below the rule review floor."),
    "ERR_MATCH_REPORT_EXCEEDS_DISPATCH": (422, "The reported counts exceed the dispatched hash count."),
    "ERR_OVERLAP_SAME_SEGMENT": (422, "A segment cannot overlap with itself."),
    "ERR_INVALID_WINDOW": (422, "The supplied time window is not ordered correctly."),
    "ERR_FUTURE_CAPTURED_AT": (422, "captured_at may not be in the future."),
    "ERR_SUPPRESSION_WINDOW_OVERLAP": (409, "An active suppression window of this type already covers the range."),
    "ERR_ACTIVATION_COOLDOWN_VIOLATION": (409, "The destination cooldown has not elapsed."),
    "ERR_ACTIVATION_CONCURRENCY_EXCEEDED": (409, "The destination concurrency ceiling is exceeded."),
    "ERR_HASH_QUOTA_EXCEEDED": (409, "The destination daily hash quota is exhausted."),
    "ERR_RETRY_LIMIT_REACHED": (409, "The batch retry limit has been reached."),
    "ERR_INVALID_HOUSEHOLD_STATE": (409, "The household is not in a state that accepts this member."),
    "ERR_HOUSEHOLD_CAPACITY_EXCEEDED": (409, "The household is at capacity."),
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with a catalog error."""

    def __init__(self, error_id, message=None):
        status, default_message = ERROR_CATALOG.get(error_id, (400, "Request failed."))
        super().__init__(message or default_message)
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
