"""Error class and one factory per error id (PRD §5, SCAFFOLD table 6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _err(error_id, http_status):
    def make(message):
        return ApiError(error_id, http_status, message)
    make.error_id = error_id
    make.http_status = http_status
    return make


# --- Auth ---
missing_context = _err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)
forbidden_role = _err("ERR_FORBIDDEN_ROLE", 403)
# --- Existence / input ---
not_found = _err("ERR_NOT_FOUND", 404)
invalid_request = _err("ERR_INVALID_REQUEST", 400)
invalid_time_window = _err("ERR_INVALID_TIME_WINDOW", 400)
# --- Concurrency ---
stale_version = _err("ERR_STALE_VERSION", 412)
# --- State ---
invalid_state = _err("ERR_INVALID_STATE_TRANSITION", 409)
tech_pack_not_pending_review = _err("ERR_TECH_PACK_NOT_PENDING_REVIEW", 409)
tech_pack_not_editable = _err("ERR_TECH_PACK_NOT_EDITABLE", 409)
tech_pack_not_approved = _err("ERR_TECH_PACK_NOT_APPROVED", 409)
marker_not_draft = _err("ERR_MARKER_NOT_DRAFT", 409)
marker_not_approved = _err("ERR_MARKER_NOT_APPROVED", 409)
order_not_planned = _err("ERR_ORDER_NOT_PLANNED", 409)
order_not_finishable = _err("ERR_ORDER_NOT_FINISHABLE", 409)
no_approved_marker = _err("ERR_NO_APPROVED_MARKER", 409)
no_operation_specs = _err("ERR_NO_OPERATION_SPECS", 409)
trim_hold_active = _err("ERR_TRIM_HOLD_ACTIVE", 409)
bundle_not_releasable = _err("ERR_BUNDLE_NOT_RELEASABLE", 409)
bundle_not_loggable = _err("ERR_BUNDLE_NOT_LOGGABLE", 409)
operation_sequence_violation = _err("ERR_OPERATION_SEQUENCE_VIOLATION", 409)
payroll_not_open = _err("ERR_PAYROLL_NOT_OPEN", 409)
payroll_not_calculated = _err("ERR_PAYROLL_NOT_CALCULATED", 409)
payroll_not_approved = _err("ERR_PAYROLL_NOT_APPROVED", 409)
audit_not_failed = _err("ERR_AUDIT_NOT_FAILED", 409)
reaudit_parent_not_reworked = _err("ERR_REAUDIT_PARENT_NOT_REWORKED", 409)
no_completed_bundles = _err("ERR_NO_COMPLETED_BUNDLES", 409)
line_capacity_exceeded = _err("ERR_LINE_STATION_CAPACITY_EXCEEDED", 409)
operator_schedule_overlap = _err("ERR_OPERATOR_SCHEDULE_OVERLAP", 409)
duplicate_operation_sequence = _err("ERR_DUPLICATE_OPERATION_SEQUENCE", 409)
# --- Safety / compliance ---
content_claim_violation = _err("ERR_CONTENT_CLAIM_VIOLATION", 403)
not_certifiable = _err("ERR_NOT_CERTIFIABLE", 409)
sod_self_review = _err("ERR_SOD_SELF_REVIEW", 403)
sod_payroll_self_approve = _err("ERR_SOD_PAYROLL_SELF_APPROVE", 403)
sod_reaudit_self_recheck = _err("ERR_SOD_REAUDIT_SELF_RECHECK", 403)
# --- Referential / capacity / fiscal ---
reaudit_order_mismatch = _err("ERR_REAUDIT_ORDER_MISMATCH", 422)
operation_not_in_tech_pack = _err("ERR_OPERATION_NOT_IN_TECH_PACK", 422)
no_line_assignment = _err("ERR_NO_LINE_ASSIGNMENT", 422)
qty_exceeds_remaining = _err("ERR_QTY_EXCEEDS_REMAINING", 422)
cut_exceeds_uncut = _err("ERR_CUT_EXCEEDS_UNCUT", 422)
roll_not_available = _err("ERR_ROLL_NOT_AVAILABLE", 409)
insufficient_fabric = _err("ERR_INSUFFICIENT_FABRIC", 409)
