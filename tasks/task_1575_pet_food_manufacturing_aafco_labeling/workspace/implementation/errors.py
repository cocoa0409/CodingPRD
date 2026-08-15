"""Error classes and error ID constants for the Pet Food AAFCO API."""


class ApiError(Exception):
    """An error carrying the scaffold-defined error_id and HTTP status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Error ID constants (from SCAFFOLD errors catalog) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
ERR_STALE_FORMULA_VERSION = "ERR_STALE_FORMULA_VERSION"
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"
ERR_SUPPLIER_NOT_APPROVED = "ERR_SUPPLIER_NOT_APPROVED"
ERR_SUPPLIER_SUSPENDED = "ERR_SUPPLIER_SUSPENDED"
ERR_OPEN_RECALL = "ERR_OPEN_RECALL"
ERR_INGREDIENT_INACTIVE = "ERR_INGREDIENT_INACTIVE"
ERR_UNAPPROVED_INGREDIENT_SOURCE = "ERR_UNAPPROVED_INGREDIENT_SOURCE"
ERR_INCLUSION_SUM_INVALID = "ERR_INCLUSION_SUM_INVALID"
ERR_SUBSTANTIATION_UNMET = "ERR_SUBSTANTIATION_UNMET"
ERR_LINE_SCHEDULE_CONFLICT = "ERR_LINE_SCHEDULE_CONFLICT"
ERR_BEST_BY_INVALID = "ERR_BEST_BY_INVALID"
ERR_LABEL_REVISION_STALE = "ERR_LABEL_REVISION_STALE"
ERR_COMPLAINT_SCORE_HOLD = "ERR_COMPLAINT_SCORE_HOLD"
ERR_YIELD_VARIANCE_HOLD = "ERR_YIELD_VARIANCE_HOLD"
ERR_DUPLICATE_KEY = "ERR_DUPLICATE_KEY"
ERR_TRIAL_NOT_FULLY_ENROLLED = "ERR_TRIAL_NOT_FULLY_ENROLLED"
ERR_TRIAL_COMPLETION_LOW = "ERR_TRIAL_COMPLETION_LOW"
ERR_ADVERSE_CLOSE_FORBIDDEN = "ERR_ADVERSE_CLOSE_FORBIDDEN"
ERR_RECALL_NO_LOTS = "ERR_RECALL_NO_LOTS"
ERR_RECALL_SCOPE_EMPTY = "ERR_RECALL_SCOPE_EMPTY"
ERR_EFFECTIVENESS_RANGE = "ERR_EFFECTIVENESS_RANGE"
ERR_SAMPLE_PENDING = "ERR_SAMPLE_PENDING"
ERR_PROFILE_BASIS_MISMATCH = "ERR_PROFILE_BASIS_MISMATCH"
ERR_PAGINATION = "ERR_PAGINATION"


def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def unauthorized_role(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED_ROLE, msg, 403)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def invalid_state(msg="Requested transition does not exist from current state"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def already_terminal(msg="Entity is in a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, msg, 409)


def stale_formula_version(msg="expected_formula_version does not match current version"):
    return ApiError(ERR_STALE_FORMULA_VERSION, msg, 412)


def sod_violation(msg="Approver/rejecter must differ from the requester"):
    return ApiError(ERR_SOD_VIOLATION, msg, 403)


def supplier_not_approved(msg="Supplier is not in APPROVED state"):
    return ApiError(ERR_SUPPLIER_NOT_APPROVED, msg, 422)


def supplier_suspended(msg="A supplier behind an approved pairing is suspended"):
    return ApiError(ERR_SUPPLIER_SUSPENDED, msg, 422)


def open_recall(msg="Formula has an open recall"):
    return ApiError(ERR_OPEN_RECALL, msg, 422)


def ingredient_inactive(msg="A referenced ingredient is RETIRED"):
    return ApiError(ERR_INGREDIENT_INACTIVE, msg, 422)


def unapproved_ingredient_source(msg="No APPROVED supplier pairing covers every formula ingredient"):
    return ApiError(ERR_UNAPPROVED_INGREDIENT_SOURCE, msg, 422)


def inclusion_sum_invalid(msg="Inclusion percentages must total 100.00 +/- 0.01"):
    return ApiError(ERR_INCLUSION_SUM_INVALID, msg, 422)


def substantiation_unmet(msg="Adequacy-basis gate failed"):
    return ApiError(ERR_SUBSTANTIATION_UNMET, msg, 422)


def line_schedule_conflict(msg="Production window overlaps another active batch on this line"):
    return ApiError(ERR_LINE_SCHEDULE_CONFLICT, msg, 409)


def best_by_invalid(msg="best_by_date must be strictly after the production date"):
    return ApiError(ERR_BEST_BY_INVALID, msg, 422)


def label_revision_stale(msg="label_revision_ref differs from current Formula.revision_number"):
    return ApiError(ERR_LABEL_REVISION_STALE, msg, 422)


def complaint_score_hold(msg="BrandOwner.complaint_score >= 70.0 blocks approval"):
    return ApiError(ERR_COMPLAINT_SCORE_HOLD, msg, 422)


def yield_variance_hold(msg="|yield_variance_pct| > 5.00 requires QualityAnalyst override"):
    return ApiError(ERR_YIELD_VARIANCE_HOLD, msg, 422)


def duplicate_key(msg="Uniqueness constraint violated"):
    return ApiError(ERR_DUPLICATE_KEY, msg, 409)


def trial_not_fully_enrolled(msg="start-trial requires enrolled_count >= animal_count"):
    return ApiError(ERR_TRIAL_NOT_FULLY_ENROLLED, msg, 422)


def trial_completion_low(msg="completion_ratio < 0.75; cannot record explicit pass"):
    return ApiError(ERR_TRIAL_COMPLETION_LOW, msg, 422)


def adverse_close_forbidden(msg="close-no-action forbidden for adverse-event cases"):
    return ApiError(ERR_ADVERSE_CLOSE_FORBIDDEN, msg, 422)


def recall_no_lots(msg="affected_lot_count must be > 0"):
    return ApiError(ERR_RECALL_NO_LOTS, msg, 422)


def recall_scope_empty(msg="Recall initiation found no in-scope batches or lots"):
    return ApiError(ERR_RECALL_SCOPE_EMPTY, msg, 422)


def effectiveness_range(msg="effectiveness_pct outside [0, 100]"):
    return ApiError(ERR_EFFECTIVENESS_RANGE, msg, 422)


def sample_pending(msg="At least one LabSample with verdict != PENDING required"):
    return ApiError(ERR_SAMPLE_PENDING, msg, 422)


def profile_basis_mismatch(msg="Profile/protocol basis mismatch with formula adequacy_basis"):
    return ApiError(ERR_PROFILE_BASIS_MISMATCH, msg, 422)


def pagination_error(msg="limit outside [1,100] or offset < 0"):
    return ApiError(ERR_PAGINATION, msg, 400)
