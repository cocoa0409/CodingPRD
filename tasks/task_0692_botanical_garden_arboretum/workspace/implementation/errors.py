"""Error classes and error ID constants (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog: id -> http status (PRD §5) ------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_CROSS_GARDEN_REFERENCE = "ERR_CROSS_GARDEN_REFERENCE"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_MEMBERSHIP_VERSION = "ERR_STALE_MEMBERSHIP_VERSION"
ERR_MEMBERSHIP_NOT_ACTIVE = "ERR_MEMBERSHIP_NOT_ACTIVE"
ERR_INVALID_WINDOW = "ERR_INVALID_WINDOW"
ERR_HOUSEHOLD_CAP_EXCEEDED = "ERR_HOUSEHOLD_CAP_EXCEEDED"
ERR_INSUFFICIENT_GUEST_PASSES = "ERR_INSUFFICIENT_GUEST_PASSES"
ERR_RECIPROCAL_NOT_ELIGIBLE = "ERR_RECIPROCAL_NOT_ELIGIBLE"
ERR_VENUE_DOUBLE_BOOKED = "ERR_VENUE_DOUBLE_BOOKED"
ERR_SLOT_CAPACITY_EXCEEDED = "ERR_SLOT_CAPACITY_EXCEEDED"
ERR_SESSION_CLOSED = "ERR_SESSION_CLOSED"
ERR_PLAN_INACTIVE = "ERR_PLAN_INACTIVE"
ERR_RENEWAL_WINDOW_NOT_OPEN = "ERR_RENEWAL_WINDOW_NOT_OPEN"
ERR_DONATION_VOIDED = "ERR_DONATION_VOIDED"
ERR_CAMPAIGN_CLOSED = "ERR_CAMPAIGN_CLOSED"
ERR_FUND_ALREADY_EXISTS = "ERR_FUND_ALREADY_EXISTS"
ERR_INVALID_HEAD_SPLIT = "ERR_INVALID_HEAD_SPLIT"
ERR_REFUND_NOT_ALLOWED = "ERR_REFUND_NOT_ALLOWED"


# --- Convenience constructors ----------------------------------------------
def unauthenticated(msg="Missing X-User-ID or X-User-Role header"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="Visitor is not the owning member of this resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def validation(msg="Malformed request body"):
    return ApiError(ERR_VALIDATION, 422, msg)


def cross_garden_reference(msg="Referenced resource belongs to a different garden"):
    return ApiError(ERR_CROSS_GARDEN_REFERENCE, 422, msg)


def invalid_state(msg="Resource not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_membership_version(msg="expected_membership_version does not match current version"):
    return ApiError(ERR_STALE_MEMBERSHIP_VERSION, 412, msg)


def membership_not_active(msg="Attached membership is not ACTIVE"):
    return ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409, msg)


def invalid_window(msg="ends_at must be strictly after starts_at"):
    return ApiError(ERR_INVALID_WINDOW, 422, msg)


def household_cap_exceeded(msg="household_member_names violates the tier/cap rule"):
    return ApiError(ERR_HOUSEHOLD_CAP_EXCEEDED, 422, msg)


def insufficient_guest_passes(msg="guest_heads exceeds guest_passes_remaining"):
    return ApiError(ERR_INSUFFICIENT_GUEST_PASSES, 409, msg)


def reciprocal_not_eligible(msg="reciprocal reservation is not eligible"):
    return ApiError(ERR_RECIPROCAL_NOT_ELIGIBLE, 422, msg)


def venue_double_booked(msg="Confirmation collides with an existing CONFIRMED rental"):
    return ApiError(ERR_VENUE_DOUBLE_BOOKED, 409, msg)


def slot_capacity_exceeded(msg="party_size would exceed slot capacity"):
    return ApiError(ERR_SLOT_CAPACITY_EXCEEDED, 409, msg)


def session_closed(msg="Program session is CLOSED"):
    return ApiError(ERR_SESSION_CLOSED, 409, msg)


def plan_inactive(msg="MembershipPlan is not active"):
    return ApiError(ERR_PLAN_INACTIVE, 409, msg)


def renewal_window_not_open(msg="Renewal window is not open and auto_renew is false"):
    return ApiError(ERR_RENEWAL_WINDOW_NOT_OPEN, 409, msg)


def donation_voided(msg="Donation is already VOIDED"):
    return ApiError(ERR_DONATION_VOIDED, 409, msg)


def campaign_closed(msg="Conservancy campaign is already CLOSED"):
    return ApiError(ERR_CAMPAIGN_CLOSED, 409, msg)


def fund_already_exists(msg="A conservancy fund already exists for this garden"):
    return ApiError(ERR_FUND_ALREADY_EXISTS, 409, msg)


def invalid_head_split(msg="Invalid reservation head split"):
    return ApiError(ERR_INVALID_HEAD_SPLIT, 422, msg)


def refund_not_allowed(msg="Ticket is not in PURCHASED status"):
    return ApiError(ERR_REFUND_NOT_ALLOWED, 409, msg)
