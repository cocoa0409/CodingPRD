"""Error catalog (PRD §5, SCAFFOLD §1.6) — every error_id verbatim."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Error ID constants (SCAFFOLD §1.6) -------------------------------------
ERR_MISSING_CONTEXT = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_INSUFFICIENT_PERMISSIONS = "ERR_INSUFFICIENT_PERMISSIONS"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION_PARAMETERS"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_UNRESOLVED_PILOTS = "ERR_UNRESOLVED_PILOTS"
ERR_OPEN_WORK_REMAINS = "ERR_OPEN_WORK_REMAINS"
ERR_PILOT_NOT_STARTED = "ERR_PILOT_NOT_STARTED"
ERR_PUBLIC_REVIEW_NOT_CLOSED = "ERR_PUBLIC_REVIEW_NOT_CLOSED"
ERR_CHALLENGE_WINDOW_CLOSED = "ERR_CHALLENGE_WINDOW_CLOSED"
ERR_APPEAL_WINDOW_CLOSED = "ERR_APPEAL_WINDOW_CLOSED"
ERR_PILOT_WINDOW_CONFLICT = "ERR_PILOT_WINDOW_CONFLICT"
ERR_PUBLIC_REVIEW_WINDOW_CONFLICT = "ERR_PUBLIC_REVIEW_WINDOW_CONFLICT"
ERR_MATERIAL_FROZEN = "ERR_MATERIAL_FROZEN"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_ALIGNMENT_COVERAGE = "ERR_ALIGNMENT_COVERAGE_BELOW_THRESHOLD"
ERR_NO_VETTED_MATERIALS = "ERR_NO_VETTED_MATERIALS"
ERR_COMPOSITE_BELOW_THRESHOLD = "ERR_COMPOSITE_BELOW_THRESHOLD"
ERR_PARTICIPATION_BELOW_FLOOR = "ERR_PARTICIPATION_BELOW_FLOOR"
ERR_BID_RULE_NOT_SATISFIED = "ERR_BID_RULE_NOT_SATISFIED"
ERR_QUOTE_NOT_AWARD_WINNER = "ERR_QUOTE_NOT_AWARD_WINNER"
ERR_QUOTE_NOT_SELECTED = "ERR_QUOTE_NOT_SELECTED"
ERR_QUOTE_MATERIAL_MISMATCH = "ERR_QUOTE_MATERIAL_MISMATCH"
ERR_INSUFFICIENT_INVENTORY = "ERR_INSUFFICIENT_INVENTORY"
ERR_OVER_RECEIPT = "ERR_OVER_RECEIPT"
ERR_PO_NOT_CLOSABLE = "ERR_PO_NOT_CLOSABLE"
ERR_PAYMENT_EXCEEDS_BALANCE = "ERR_PAYMENT_EXCEEDS_BALANCE"
ERR_QUORUM_NOT_MET = "ERR_QUORUM_NOT_MET"
ERR_DUPLICATE_VOTE = "ERR_DUPLICATE_VOTE"
ERR_DUPLICATE_REVIEW = "ERR_DUPLICATE_REVIEW"
ERR_OPEN_CHALLENGE_EXISTS = "ERR_OPEN_CHALLENGE_EXISTS"
ERR_FRAMEWORK_MISMATCH = "ERR_FRAMEWORK_MISMATCH"
ERR_MATERIAL_NOT_ADOPTED = "ERR_MATERIAL_NOT_ADOPTED"
ERR_CHALLENGE_TARGET_INVALID = "ERR_CHALLENGE_TARGET_INVALID"
ERR_BUDGET_ENVELOPE_EXCEEDED = "ERR_BUDGET_ENVELOPE_EXCEEDED"
ERR_STALE_CYCLE_VERSION = "ERR_STALE_CYCLE_VERSION"


# --- Constructors ------------------------------------------------------------

def missing_context():
    return ApiError(ERR_MISSING_CONTEXT, 400,
                    "X-User-ID and X-User-Role headers are required and the role "
                    "must be one of the nine declared roles")


def insufficient_permissions(msg="role is not authorized for this endpoint"):
    return ApiError(ERR_INSUFFICIENT_PERMISSIONS, 403, msg)


def not_found(resource_type):
    return ApiError(ERR_NOT_FOUND, 404, "%s not found" % resource_type)


def validation(msg):
    return ApiError(ERR_VALIDATION, 400, msg)


def invalid_pagination(msg="limit must be within 1..100 and offset >= 0"):
    return ApiError(ERR_INVALID_PAGINATION, 400, msg)


def invalid_state(msg="entity is not in the required state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def conflict(error_id, msg):
    return ApiError(error_id, 409, msg)


def stale_cycle_version():
    return ApiError(ERR_STALE_CYCLE_VERSION, 412,
                    "expected_cycle_version does not match the adoption cycle's "
                    "current version")


def budget_exceeded(msg="insufficient available balance on the cycle ledger"):
    return ApiError(ERR_BUDGET_ENVELOPE_EXCEEDED, 402, msg)
