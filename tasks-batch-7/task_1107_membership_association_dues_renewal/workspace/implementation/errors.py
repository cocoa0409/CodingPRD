"""Error classes and error ID constants — from SCAFFOLD.yaml error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Error catalog (SCAFFOLD Table 6 / PRD §5) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_DUPLICATE_EMAIL = "ERR_DUPLICATE_EMAIL"            # 409
ERR_DUPLICATE_CATEGORY_CODE = "ERR_DUPLICATE_CATEGORY_CODE"  # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_SCHEDULE_OVERLAP = "ERR_SCHEDULE_OVERLAP"          # 409
ERR_INCREASE_NOTICE_GAP = "ERR_INCREASE_NOTICE_GAP"    # 409
ERR_INACTIVE_REFERENCE = "ERR_INACTIVE_REFERENCE"      # 422
ERR_RETRY_EXHAUSTED = "ERR_RETRY_EXHAUSTED"            # 422
ERR_AUTO_RENEW_NOT_ALLOWED = "ERR_AUTO_RENEW_NOT_ALLOWED"  # 422
ERR_REINSTATEMENT_WINDOW_EXPIRED = "ERR_REINSTATEMENT_WINDOW_EXPIRED"  # 422
ERR_REFUND_WINDOW_EXPIRED = "ERR_REFUND_WINDOW_EXPIRED"    # 422
ERR_INVALID_REVENUE_KIND = "ERR_INVALID_REVENUE_KIND"  # 422
ERR_INVOICE_NOT_SETTLED = "ERR_INVOICE_NOT_SETTLED"    # 422
ERR_VERIFICATION_BLOCKED = "ERR_VERIFICATION_BLOCKED"  # 422
ERR_MEMBER_NOT_GRACE = "ERR_MEMBER_NOT_GRACE"          # 409
ERR_REINSTATEMENT_HAS_PENDING = "ERR_REINSTATEMENT_HAS_PENDING"  # 409
ERR_NO_AUTO_RENEW_ACTIVE = "ERR_NO_AUTO_RENEW_ACTIVE"  # 409


def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="Referenced id does not exist"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_state(msg="Resource is in wrong state for requested transition"):
    return ApiError(ERR_INVALID_STATE, msg, 409)
