"""Domain error definitions for the FCRA API.

All error_ids are read straight from the scaffold's error catalog. The
helpers below are simple factories so call sites can stay terse.
"""


class APIError(Exception):
    """Structured error carrying error_id + HTTP status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_auth_required(msg="Missing or empty X-User-ID / X-User-Role header."):
    return APIError("ERR_AUTH_REQUIRED", msg, 401)


def err_forbidden(msg="Role not permitted for this endpoint."):
    return APIError("ERR_FORBIDDEN", msg, 403)


def err_candidate_not_found(msg="Candidate not found."):
    return APIError("ERR_CANDIDATE_NOT_FOUND", msg, 404)


def err_order_not_found(msg="BackgroundCheckOrder not found."):
    return APIError("ERR_ORDER_NOT_FOUND", msg, 404)


def err_resource_not_found(msg="Resource not found."):
    return APIError("ERR_RESOURCE_NOT_FOUND", msg, 404)


def err_invalid_state(msg="Target resource is not in a legal state for this transition."):
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_ban_the_box(msg="Order opened earlier than the jurisdiction's ban_the_box_stage gate."):
    return APIError("ERR_BAN_THE_BOX_VIOLATION", msg, 422)


def err_salary_history_ban(msg="salary_history is forbidden for this candidate / jurisdiction."):
    return APIError("ERR_SALARY_HISTORY_BAN", msg, 422)


def err_consent_invalid(msg="ConsentDisclosure is missing, not ACTIVE, or otherwise unusable."):
    return APIError("ERR_CONSENT_INVALID", msg, 422)


def err_consent_timestamp_invalid(
    msg="consent_timestamp > now() OR disclosure_presented_at > consent_timestamp.",
):
    return APIError("ERR_CONSENT_TIMESTAMP_INVALID", msg, 422)


def err_consent_candidate_mismatch(
    msg="consent_disclosure_id refers to a different candidate.",
):
    return APIError("ERR_CONSENT_CANDIDATE_MISMATCH", msg, 422)


def err_sod_violation(msg="Segregation-of-duties violation."):
    return APIError("ERR_SOD_VIOLATION", msg, 422)


def err_cooling_off_not_elapsed(msg="Cooling-off window has not yet elapsed."):
    return APIError("ERR_COOLING_OFF_NOT_ELAPSED", msg, 422)


def err_open_dispute_blocks_final(
    msg="An OPEN Dispute exists on this order; Final Adverse Action is blocked.",
):
    return APIError("ERR_OPEN_DISPUTE_BLOCKS_FINAL", msg, 422)


def err_package_set_invalid(msg="requested_packages is empty, duplicated, or unknown."):
    return APIError("ERR_PACKAGE_SET_INVALID", msg, 422)


def err_candidate_not_eligible(msg="Candidate.eligibility_posture is not ELIGIBLE."):
    return APIError("ERR_CANDIDATE_NOT_ELIGIBLE", msg, 422)


def err_dispute_not_owned(msg="Dispute is not on an item owned by the calling candidate."):
    return APIError("ERR_DISPUTE_NOT_OWNED", msg, 403)


def err_rework_cap_exceeded(msg="VerificationItem.rework_count would exceed 2."):
    return APIError("ERR_REWORK_CAP_EXCEEDED", msg, 422)


def err_audit_chain_broken(msg="AuditEvent.previous_event_id breaks the audit chain."):
    return APIError("ERR_AUDIT_CHAIN_BROKEN", msg, 422)


def err_candidate_email_taken(msg="A non-archived candidate already has this email."):
    return APIError("ERR_CANDIDATE_EMAIL_TAKEN", msg, 409)


def err_adverse_flow_already_exists(msg="An AdverseActionFlow already exists for this order."):
    return APIError("ERR_ADVERSE_FLOW_ALREADY_EXISTS", msg, 409)


def err_stale_version(msg="version does not match current row version."):
    return APIError("ERR_STALE_VERSION", msg, 409)


def err_validation_failed(msg="Required field missing, malformed JSON, or type mismatch."):
    return APIError("ERR_VALIDATION_FAILED", msg, 400)
