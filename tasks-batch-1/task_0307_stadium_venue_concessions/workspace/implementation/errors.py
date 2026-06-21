"""Error classes and error-id constants for the Stadium Venue Concessions API.

Every error_id and HTTP status traces to PRD §5 (Error Code Catalogue) and
SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """An error that maps to the standard error envelope (PRD §2.2)."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http_status (PRD §5 / SCAFFOLD §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_NOT_ORDER_OWNER = "ERR_NOT_ORDER_OWNER"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_STAND_VERSION = "ERR_STALE_STAND_VERSION"
ERR_EVENT_NOT_OPENABLE = "ERR_EVENT_NOT_OPENABLE"
ERR_UNDERSTAFFED_OPEN = "ERR_UNDERSTAFFED_OPEN"
ERR_STAND_NOT_OPEN = "ERR_STAND_NOT_OPEN"
ERR_ORDER_UNPAID = "ERR_ORDER_UNPAID"
ERR_LOT_NOT_EXPIRED = "ERR_LOT_NOT_EXPIRED"
ERR_CROSS_EVENT_TRANSFER = "ERR_CROSS_EVENT_TRANSFER"
ERR_EVENT_WINDOW_OVERLAP = "ERR_EVENT_WINDOW_OVERLAP"
ERR_SHIFT_OVERLAP = "ERR_SHIFT_OVERLAP"
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"
ERR_TRANSFER_QTY_EXCEEDS_ONHAND = "ERR_TRANSFER_QTY_EXCEEDS_ONHAND"
ERR_EVENT_NOT_SETTLEABLE = "ERR_EVENT_NOT_SETTLEABLE"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


def unauthenticated(msg="Missing authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role not permitted for this endpoint."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def not_order_owner(msg="Patron is not the owner of this order."):
    return ApiError(ERR_NOT_ORDER_OWNER, 403, msg)


def invalid_state(msg="Requested transition is not defined from current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_stand_version(msg="Stand version is stale."):
    return ApiError(ERR_STALE_STAND_VERSION, 412, msg)


def event_not_openable(msg="Parent event is not DOORS_OPEN or IN_PROGRESS."):
    return ApiError(ERR_EVENT_NOT_OPENABLE, 409, msg)


def understaffed_open(msg="Stand has no checked-in staff."):
    return ApiError(ERR_UNDERSTAFFED_OPEN, 409, msg)


def stand_not_open(msg="Stand is not OPEN."):
    return ApiError(ERR_STAND_NOT_OPEN, 409, msg)


def order_unpaid(msg="Order is not PAID."):
    return ApiError(ERR_ORDER_UNPAID, 409, msg)


def lot_not_expired(msg="Lot is not expired."):
    return ApiError(ERR_LOT_NOT_EXPIRED, 409, msg)


def cross_event_transfer(msg="Transfer stands are not same-event distinct stands."):
    return ApiError(ERR_CROSS_EVENT_TRANSFER, 422, msg)


def event_window_overlap(msg="Event operating window overlaps another event."):
    return ApiError(ERR_EVENT_WINDOW_OVERLAP, 409, msg)


def shift_overlap(msg="Staff shift overlaps another shift for the same worker."):
    return ApiError(ERR_SHIFT_OVERLAP, 409, msg)


def insufficient_stock(msg="Insufficient on-hand stock for the order line."):
    return ApiError(ERR_INSUFFICIENT_STOCK, 409, msg)


def transfer_qty_exceeds_onhand(msg="Transfer qty exceeds source on-hand."):
    return ApiError(ERR_TRANSFER_QTY_EXCEEDS_ONHAND, 409, msg)


def event_not_settleable(msg="Event cannot be settled in its current child state."):
    return ApiError(ERR_EVENT_NOT_SETTLEABLE, 409, msg)


def invalid_request(msg="Malformed request body."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)
