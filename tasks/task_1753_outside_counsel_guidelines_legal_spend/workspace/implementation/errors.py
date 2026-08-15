"""Error classes and error ID constants for the Outside Counsel Spend API."""


class ApiError(Exception):
    """Exception carrying an error_id, message, and HTTP status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (from SCAFFOLD §1.6 / PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                            # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                    # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                    # 412
ERR_FIRM_MISMATCH = "ERR_FIRM_MISMATCH"                    # 403
ERR_FIRM_NOT_ACTIVE = "ERR_FIRM_NOT_ACTIVE"                # 409
ERR_ACK_OUTSTANDING = "ERR_ACK_OUTSTANDING"                # 409
ERR_GUIDELINE_OVERLAP = "ERR_GUIDELINE_OVERLAP"            # 409
ERR_NOTICE_GAP_VIOLATION = "ERR_NOTICE_GAP_VIOLATION"      # 409
ERR_TIMEKEEPER_NOT_QUALIFIED = "ERR_TIMEKEEPER_NOT_QUALIFIED"  # 422
ERR_RATE_CARD_YEAR_CONFLICT = "ERR_RATE_CARD_YEAR_CONFLICT"    # 409
ERR_DUPLICATE_INVOICE_NUMBER = "ERR_DUPLICATE_INVOICE_NUMBER"  # 409
ERR_INVALID_TEMPORAL = "ERR_INVALID_TEMPORAL"              # 422
ERR_MATTER_HAS_OPEN_INVOICES = "ERR_MATTER_HAS_OPEN_INVOICES"  # 409
ERR_MATTER_HAS_OPEN_APPEALS = "ERR_MATTER_HAS_OPEN_APPEALS"    # 409
ERR_FIRM_HAS_OPEN_INVOICES = "ERR_FIRM_HAS_OPEN_INVOICES"      # 409
ERR_OPEN_APPEALS = "ERR_OPEN_APPEALS"                      # 409
ERR_INVALID_ADJUSTMENT = "ERR_INVALID_ADJUSTMENT"          # 422
ERR_REFERENTIAL_INTEGRITY = "ERR_REFERENTIAL_INTEGRITY"    # 422
ERR_TIMEKEEPER_HAS_PENDING_LINES = "ERR_TIMEKEEPER_HAS_PENDING_LINES"  # 409
ERR_OVER_BUDGET = "ERR_OVER_BUDGET"                        # 422 (line-level only)


def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="Role is not permitted on this endpoint"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="Path-template resource does not exist within the expected scope"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_state(msg="Requested transition is not allowed from the resource's current state"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def stale_version(msg="OCC expected_*_version does not match the parent's current version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def firm_mismatch(msg="Acting PanelFirmUser's firm does not match the target resource's owning firm"):
    return ApiError(ERR_FIRM_MISMATCH, msg, 403)


def firm_not_active(msg="PanelFirm.status is not ACTIVE for an operation that requires it"):
    return ApiError(ERR_FIRM_NOT_ACTIVE, msg, 409)


def ack_outstanding(msg="Firm has not acknowledged the currently-published GuidelineVersion"):
    return ApiError(ERR_ACK_OUTSTANDING, msg, 409)


def guideline_overlap(msg="Another PUBLISHED GuidelineVersion has effective_date >= the one being published"):
    return ApiError(ERR_GUIDELINE_OVERLAP, msg, 409)


def notice_gap(msg="New guideline's effective_date is too close to the prior version's"):
    return ApiError(ERR_NOTICE_GAP_VIOLATION, msg, 409)


def timekeeper_not_qualified(msg="A TimekeeperRate references a timekeeper whose qualification_status != QUALIFIED"):
    return ApiError(ERR_TIMEKEEPER_NOT_QUALIFIED, msg, 422)


def rate_card_year_conflict(msg="Another SUBMITTED or APPROVED rate card already covers this effective_year for this firm"):
    return ApiError(ERR_RATE_CARD_YEAR_CONFLICT, msg, 409)


def duplicate_invoice_number(msg="An invoice with this invoice_number already exists for the firm"):
    return ApiError(ERR_DUPLICATE_INVOICE_NUMBER, msg, 409)


def invalid_temporal(msg="billing_period_end <= billing_period_start, guideline effective_date in the past, or accrual period in the future"):
    return ApiError(ERR_INVALID_TEMPORAL, msg, 422)


def matter_has_open_invoices(msg="Matter cannot close while invoices are SUBMITTED or UNDER_REVIEW"):
    return ApiError(ERR_MATTER_HAS_OPEN_INVOICES, msg, 409)


def matter_has_open_appeals(msg="Matter cannot close while appeals are SUBMITTED or UNDER_REVIEW"):
    return ApiError(ERR_MATTER_HAS_OPEN_APPEALS, msg, 409)


def firm_has_open_invoices(msg="Firm cannot offboard while invoices are SUBMITTED or UNDER_REVIEW"):
    return ApiError(ERR_FIRM_HAS_OPEN_INVOICES, msg, 409)


def open_appeals(msg="Invoice cannot be paid while any line-item appeal is SUBMITTED or UNDER_REVIEW"):
    return ApiError(ERR_OPEN_APPEALS, msg, 409)


def invalid_adjustment(msg="adjusted_amount_cents out of range (must be >= 0 and < amount_cents)"):
    return ApiError(ERR_INVALID_ADJUSTMENT, msg, 422)


def referential_integrity(msg="FK reference does not resolve within scope"):
    return ApiError(ERR_REFERENTIAL_INTEGRITY, msg, 422)


def timekeeper_has_pending_lines(msg="Timekeeper cannot be disqualified while PENDING line items reference them"):
    return ApiError(ERR_TIMEKEEPER_HAS_PENDING_LINES, msg, 409)
