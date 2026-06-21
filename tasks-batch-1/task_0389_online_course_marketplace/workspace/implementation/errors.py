"""Error classes and the complete error catalog (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> (http_status, default message)
CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Missing or invalid authentication headers."),
    "ERR_FORBIDDEN": (403, "Role not permitted or resource not owned by caller."),
    "ERR_NOT_FOUND": (404, "Referenced resource does not exist."),
    "ERR_INVALID_REQUEST": (400, "Invalid request: missing field, bad enum, or out-of-range value."),
    "ERR_INVALID_STATE": (409, "Resource is not in a state that permits this transition."),
    "ERR_COURSE_NOT_PUBLISHABLE": (422, "Course cannot be published in its current configuration."),
    "ERR_DUPLICATE_LESSON_COMPLETION": (409, "Lesson completion already exists or order_index collides."),
    "ERR_LESSON_LOCKED": (409, "Drip-gated lesson is not yet unlocked."),
    "ERR_COUPON_NOT_REDEEMABLE": (422, "Coupon is outside its window or not active."),
    "ERR_COUPON_COURSE_MISMATCH": (422, "Coupon does not apply to the enrolled course."),
    "ERR_COUPON_EXHAUSTED": (409, "Coupon has reached its maximum redemptions."),
    "ERR_ALREADY_ENROLLED": (409, "Learner already has an enrollment for this course."),
    "ERR_REVIEW_NOT_ELIGIBLE": (422, "Enrollment is not eligible for a review."),
    "ERR_INVALID_BUNDLE": (422, "Bundle configuration is invalid."),
    "ERR_COUPON_WINDOW_OVERLAP": (409, "Coupon window overlaps an existing coupon."),
    "ERR_BUNDLE_PROMO_OVERLAP": (409, "Bundle promo window collides with an existing bundle."),
    "ERR_INSUFFICIENT_BALANCE": (422, "Instructor payout balance is insufficient."),
    "ERR_REFUND_WINDOW_CLOSED": (422, "Refund window has closed."),
    "ERR_STALE_VERSION": (412, "Optimistic concurrency version mismatch."),
}


def err(error_id, message=None):
    http = CATALOG.get(error_id, (400, error_id))[0]
    if message is None:
        message = CATALOG.get(error_id, (None, error_id))[1]
    return ApiError(error_id, http, message)
