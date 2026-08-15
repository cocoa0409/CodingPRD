"""Error classes carrying error_id, message, and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Auth ---
def err_unauthenticated(msg="Missing or invalid X-User-Role or X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden_role(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", msg, 403)


def err_not_resource_owner(msg="Licensee may only act on its own resources"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", msg, 403)


# --- Validation ---
def err_validation(msg="Request body schema violation"):
    return ApiError("ERR_VALIDATION", msg, 400)


# --- Not found ---
def err_licensee_not_found(msg="Licensee not found"):
    return ApiError("ERR_LICENSEE_NOT_FOUND", msg, 404)


def err_agreement_not_found(msg="License agreement not found"):
    return ApiError("ERR_AGREEMENT_NOT_FOUND", msg, 404)


def err_report_not_found(msg="Royalty report not found"):
    return ApiError("ERR_REPORT_NOT_FOUND", msg, 404)


def err_audit_not_found(msg="Royalty audit not found"):
    return ApiError("ERR_AUDIT_NOT_FOUND", msg, 404)


def err_finding_not_found(msg="Audit finding not found"):
    return ApiError("ERR_FINDING_NOT_FOUND", msg, 404)


def err_dispute_not_found(msg="Dispute not found"):
    return ApiError("ERR_DISPUTE_NOT_FOUND", msg, 404)


def err_sublicense_not_found(msg="Sublicense grant not found"):
    return ApiError("ERR_SUBLICENSE_NOT_FOUND", msg, 404)


def err_run_not_found(msg="Distribution run not found"):
    return ApiError("ERR_RUN_NOT_FOUND", msg, 404)


# --- State ---
def err_licensee_not_active(msg="Licensee is not ACTIVE"):
    return ApiError("ERR_LICENSEE_NOT_ACTIVE", msg, 409)


def err_agreement_not_active(msg="License agreement not in the required status"):
    return ApiError("ERR_AGREEMENT_NOT_ACTIVE", msg, 409)


def err_report_invalid_state(msg="Report not in the required state"):
    return ApiError("ERR_REPORT_INVALID_STATE", msg, 409)


def err_audit_invalid_state(msg="Audit not in the required state"):
    return ApiError("ERR_AUDIT_INVALID_STATE", msg, 409)


def err_finding_not_open(msg="Finding is not OPEN"):
    return ApiError("ERR_FINDING_NOT_OPEN", msg, 409)


def err_dispute_invalid_state(msg="Dispute not in the required state"):
    return ApiError("ERR_DISPUTE_INVALID_STATE", msg, 409)


def err_run_invalid_state(msg="Distribution run not in the required state"):
    return ApiError("ERR_RUN_INVALID_STATE", msg, 409)


def err_sublicense_invalid_state(msg="Sublicense grant not in the required state"):
    return ApiError("ERR_SUBLICENSE_INVALID_STATE", msg, 409)


# --- OCC ---
def err_stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


# --- SoD ---
def err_sod_conflict(msg="Segregation of duties violated"):
    return ApiError("ERR_SOD_CONFLICT", msg, 409)


# --- Business ---
def err_report_period_overlap(msg="Report period overlaps an existing report"):
    return ApiError("ERR_REPORT_PERIOD_OVERLAP", msg, 409)


def err_audit_scope_overlap(msg="Audit scope overlaps an existing open audit"):
    return ApiError("ERR_AUDIT_SCOPE_OVERLAP", msg, 409)


def err_share_sum_invalid(msg="inventor_shares share_bp must sum to exactly 10000 with unique inventor_name"):
    return ApiError("ERR_SHARE_SUM_INVALID", msg, 422)


def err_sublicensing_not_granted(msg="Agreement does not allow sublicensing"):
    return ApiError("ERR_SUBLICENSING_NOT_GRANTED", msg, 422)


def err_duplicate_tax_id(msg="A licensee with this tax_id already exists"):
    return ApiError("ERR_DUPLICATE_TAX_ID", msg, 409)


def err_cannot_accept_own_offer(msg="Cannot accept an offer made by your own role"):
    return ApiError("ERR_CANNOT_ACCEPT_OWN_OFFER", msg, 422)


def err_period_not_closed(msg="period_end is after the current logical time"):
    return ApiError("ERR_PERIOD_NOT_CLOSED", msg, 422)


def err_audit_window_expired(msg="Audit scope is older than the audit window"):
    return ApiError("ERR_AUDIT_WINDOW_EXPIRED", msg, 422)


def err_report_not_in_audit_scope(msg="Report is not examinable within this audit's scope"):
    return ApiError("ERR_REPORT_NOT_IN_AUDIT_SCOPE", msg, 422)


def err_no_approved_sublicense(msg="Sublicense-revenue line requires an APPROVED sublicense grant"):
    return ApiError("ERR_NO_APPROVED_SUBLICENSE", msg, 422)


def err_adjustment_not_upward(msg="adjusted_base_cents must be strictly greater than royalty_base_cents"):
    return ApiError("ERR_ADJUSTMENT_NOT_UPWARD", msg, 422)


def err_pool_exceeds_undistributed(msg="pool_cents exceeds the agreement's undistributed pool"):
    return ApiError("ERR_POOL_EXCEEDS_UNDISTRIBUTED", msg, 422)
