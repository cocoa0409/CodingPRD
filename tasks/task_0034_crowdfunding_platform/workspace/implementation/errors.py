"""Error classes and error ID constants per scaffold §1.6."""


class APIError(Exception):
    """Carries error_id, message, http_status for the standard error envelope."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (mirror scaffold §1.6 error catalog)
ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
ERR_KYC_REQUIRED = "ERR_KYC_REQUIRED"
ERR_SEGREGATION_OF_DUTIES_VIOLATION = "ERR_SEGREGATION_OF_DUTIES_VIOLATION"
ERR_DEADLINE_TOO_SOON = "ERR_DEADLINE_TOO_SOON"
ERR_NO_REWARDS_DEFINED = "ERR_NO_REWARDS_DEFINED"
ERR_MODIFICATION_WINDOW_CLOSED = "ERR_MODIFICATION_WINDOW_CLOSED"
ERR_REWARD_INVENTORY_EXHAUSTED = "ERR_REWARD_INVENTORY_EXHAUSTED"
ERR_ADDON_INVENTORY_EXHAUSTED = "ERR_ADDON_INVENTORY_EXHAUSTED"
ERR_SHIPPING_ADDRESS_REQUIRED = "ERR_SHIPPING_ADDRESS_REQUIRED"
ERR_CROSS_PROJECT_REFERENCE = "ERR_CROSS_PROJECT_REFERENCE"
ERR_REFUND_EXCEEDS_REMAINDER = "ERR_REFUND_EXCEEDS_REMAINDER"
ERR_UPDATE_FREQUENCY_BREACH = "ERR_UPDATE_FREQUENCY_BREACH"
ERR_PENDING_REFUNDS_BLOCK_SETTLEMENT = "ERR_PENDING_REFUNDS_BLOCK_SETTLEMENT"
ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"
ERR_DUPLICATE_TIER_LABEL = "ERR_DUPLICATE_TIER_LABEL"
ERR_VALIDATION = "ERR_VALIDATION"


# Convenience constructors
def auth_required(msg="Missing X-User-ID or X-User-Role header"):
    return APIError(ERR_AUTH_REQUIRED, msg, 401)


def forbidden(msg="Role not authorized for this endpoint"):
    return APIError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="Resource not found"):
    return APIError(ERR_NOT_FOUND, msg, 404)


def invalid_state(msg="Operation not legal in current state"):
    return APIError(ERR_INVALID_STATE, msg, 409)


def version_conflict(msg="OCC version mismatch"):
    return APIError(ERR_VERSION_CONFLICT, msg, 409)


def kyc_required(msg="Initiator KYC verification required"):
    return APIError(ERR_KYC_REQUIRED, msg, 422)


def segregation_violation(msg="Same reviewer cannot approve multiple review stages"):
    return APIError(ERR_SEGREGATION_OF_DUTIES_VIOLATION, msg, 403)


def deadline_too_soon(msg="Project deadline must be more than 24 hours from now"):
    return APIError(ERR_DEADLINE_TOO_SOON, msg, 422)


def no_rewards(msg="Project must have at least one reward before submission"):
    return APIError(ERR_NO_REWARDS_DEFINED, msg, 422)


def modification_window_closed(msg="Order modification window has closed"):
    return APIError(ERR_MODIFICATION_WINDOW_CLOSED, msg, 422)


def reward_exhausted(msg="Reward inventory exhausted"):
    return APIError(ERR_REWARD_INVENTORY_EXHAUSTED, msg, 409)


def addon_exhausted(msg="Add-on inventory exhausted"):
    return APIError(ERR_ADDON_INVENTORY_EXHAUSTED, msg, 409)


def shipping_required(msg="Shipping address required for physical reward or shipped add-on"):
    return APIError(ERR_SHIPPING_ADDRESS_REQUIRED, msg, 422)


def cross_project(msg="Reward or add-on does not belong to this project"):
    return APIError(ERR_CROSS_PROJECT_REFERENCE, msg, 422)


def refund_exceeds(msg="Refund amount exceeds refundable remainder"):
    return APIError(ERR_REFUND_EXCEEDS_REMAINDER, msg, 422)


def update_frequency_breach(msg="Project has been silent for more than 30 days"):
    return APIError(ERR_UPDATE_FREQUENCY_BREACH, msg, 422)


def pending_refunds_block(msg="Open refund requests block settlement finalization"):
    return APIError(ERR_PENDING_REFUNDS_BLOCK_SETTLEMENT, msg, 422)


def invalid_amount(msg="Amount must be strictly greater than zero"):
    return APIError(ERR_INVALID_AMOUNT, msg, 422)


def duplicate_tier(msg="Reward tier_label is not unique within project"):
    return APIError(ERR_DUPLICATE_TIER_LABEL, msg, 422)


def validation_error(msg="Invalid request"):
    return APIError(ERR_VALIDATION, msg, 422)
