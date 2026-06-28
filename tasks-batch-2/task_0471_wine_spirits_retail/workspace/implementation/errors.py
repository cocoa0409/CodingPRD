"""Error catalog. Error IDs and HTTP statuses come verbatim from PRD §5 / SCAFFOLD errors."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Universal gates (PRD §2.10 ordering)
def unauthenticated(msg="Authentication required: X-User-Role missing or unknown."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role is not permitted to perform this operation, or ownership check failed."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="Resource is not in a state from which this transition is defined."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_order_version(msg="expected_order_version does not match the order's current version."):
    return ApiError("ERR_STALE_ORDER_VERSION", 412, msg)


def age_not_verified(msg="Acting customer is not age-verified."):
    return ApiError("ERR_AGE_NOT_VERIFIED", 422, msg)


def customer_blocked(msg="Acting customer is BLOCKED."):
    return ApiError("ERR_CUSTOMER_BLOCKED", 422, msg)


def growler_keg_state_banned(msg="GROWLER/KEG lines may not ship to this destination state."):
    return ApiError("ERR_GROWLER_KEG_STATE_BANNED", 422, msg)


def ship_state_restricted(msg="Destination state has no rule or forbids shipping."):
    return ApiError("ERR_SHIP_STATE_RESTRICTED", 422, msg)


def allocation_limit_exceeded(msg="Allocation cap per customer would be exceeded."):
    return ApiError("ERR_ALLOCATION_LIMIT_EXCEEDED", 422, msg)


def abc_monthly_limit_exceeded(msg="ABC monthly volume cap would be exceeded."):
    return ApiError("ERR_ABC_MONTHLY_LIMIT_EXCEEDED", 422, msg)


def insufficient_inventory(msg="No single inventory lot can cover the line."):
    return ApiError("ERR_INSUFFICIENT_INVENTORY", 422, msg)


def vintage_not_purchasable(msg="Vintage is not in RELEASED or ALLOCATION_OPEN status."):
    return ApiError("ERR_VINTAGE_NOT_PURCHASABLE", 422, msg)


def allocation_open_requires_flag(msg="open-allocation requires an allocated product with a non-null cap."):
    return ApiError("ERR_ALLOCATION_OPEN_REQUIRES_FLAG", 422, msg)


def release_requires_stock(msg="release requires a non-allocated product with at least one stocked lot."):
    return ApiError("ERR_RELEASE_REQUIRES_STOCK", 422, msg)


def negotiation_rounds_exceeded(msg="Negotiation round limit reached."):
    return ApiError("ERR_NEGOTIATION_ROUNDS_EXCEEDED", 422, msg)


def signature_required(msg="An adult signature is required to confirm delivery."):
    return ApiError("ERR_SIGNATURE_REQUIRED", 422, msg)


def duplicate_active_shipment(msg="Order already has a non-cancelled shipment."):
    return ApiError("ERR_DUPLICATE_ACTIVE_SHIPMENT", 409, msg)


def duplicate_membership(msg="Customer already has an ACTIVE/SUSPENDED membership."):
    return ApiError("ERR_DUPLICATE_MEMBERSHIP", 409, msg)


def shipment_channel_invalid(msg="Shipments require a READY/CAPTURED DELIVERY or SHIP order."):
    return ApiError("ERR_SHIPMENT_CHANNEL_INVALID", 422, msg)


def empty_order(msg="Order has no lines."):
    return ApiError("ERR_EMPTY_ORDER", 422, msg)


def invalid_request(msg="Field-level invalid value."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def missing_field(msg="Required request body field absent or wrong type."):
    return ApiError("ERR_MISSING_FIELD", 400, msg)


def invalid_pagination(msg="limit/offset out of range."):
    return ApiError("ERR_INVALID_PAGINATION", 400, msg)
