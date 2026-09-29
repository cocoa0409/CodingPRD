"""Error catalog (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or CATALOG.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


CATALOG = {
    # identity / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_STORE_SCOPE_VIOLATION": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_SKU_NOT_FOUND": 404,
    "ERR_INVENTORY_NOT_FOUND": 404,
    "ERR_PACKAGING_NOT_FOUND": 404,
    "ERR_PICKUP_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_ROUTING_RUN_NOT_FOUND": 404,
    "ERR_CANDIDATE_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_LINE_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_NOTIFICATION_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_STALE_PICKUP_VERSION": 412,
    "ERR_STALE_INVENTORY_VERSION": 412,
    # state
    "ERR_ASSIGNMENT_STATE_INVALID": 409,
    "ERR_ORDER_NOT_ROUTABLE": 409,
    "ERR_ORDER_LINES_LOCKED": 409,
    "ERR_NO_ROUTABLE_LINES": 409,
    "ERR_ORDER_ALREADY_SHIPPED_UNITS": 409,
    "ERR_PICKUP_STATE_INVALID": 409,
    "ERR_STORE_NODE_DEACTIVATED": 409,
    "ERR_STORE_NOT_DEACTIVATED": 409,
    "ERR_NO_OPEN_WINDOW": 409,
    # inventory floor safety
    "ERR_SAFETY_STOCK_EXCEEDS_ON_HAND": 422,
    "ERR_INVENTORY_BELOW_RESERVED": 422,
    # temporal
    "ERR_STORE_CUTOFF_PASSED": 422,
    "ERR_PICK_DEADLINE_PASSED": 422,
    "ERR_PICKUP_WINDOW_CLOSED": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_PICKUP_WINDOW_OVERLAP": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # capacity / constraint
    "ERR_LABOR_WINDOW_OVERSUBSCRIBED": 422,
    "ERR_PICKUP_CAPACITY_EXCEEDED": 422,
    "ERR_PACKAGING_DEPLETED": 422,
    "ERR_PACKAGE_TYPE_TOO_SMALL": 422,
    "ERR_PICK_UNITS_INVALID": 422,
    "ERR_ZERO_PICK_NOT_ALLOWED": 422,
    # uniqueness
    "ERR_DUPLICATE_STORE_CODE": 409,
    "ERR_DUPLICATE_SKU_CODE": 409,
    "ERR_DUPLICATE_ORDER_CODE": 409,
    "ERR_DUPLICATE_INVENTORY_ROW": 409,
    "ERR_DUPLICATE_PACKAGING_ROW": 409,
    # referential coupling
    "ERR_PICKUP_STORE_MISMATCH": 409,
    "ERR_ASSIGNMENT_LINE_MISMATCH": 409,
    "ERR_PICKUP_HAS_PARCELS": 409,
    # fiscal guardrail
    "ERR_COST_INDEX_GUARDRAIL": 422,
    # fallback
    "ERR_NOT_FOUND": 404,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_FORBIDDEN_ROLE": "The acting role may not perform this operation.",
    "ERR_STORE_SCOPE_VIOLATION": "The acting associate is not scoped to this node.",
    "ERR_INVALID_REQUEST": "The request payload or query is malformed.",
    "ERR_STORE_NOT_FOUND": "Store not found.",
    "ERR_SKU_NOT_FOUND": "Sku not found.",
    "ERR_INVENTORY_NOT_FOUND": "Store inventory row not found.",
    "ERR_PACKAGING_NOT_FOUND": "Packaging supply row not found.",
    "ERR_PICKUP_NOT_FOUND": "Carrier pickup not found.",
    "ERR_ORDER_NOT_FOUND": "Customer order not found.",
    "ERR_ORDER_LINE_NOT_FOUND": "Order line not found.",
    "ERR_ROUTING_RUN_NOT_FOUND": "Routing run not found.",
    "ERR_CANDIDATE_NOT_FOUND": "Routing candidate not found.",
    "ERR_ASSIGNMENT_NOT_FOUND": "Fulfillment assignment not found.",
    "ERR_ASSIGNMENT_LINE_NOT_FOUND": "Assignment line not found.",
    "ERR_WINDOW_NOT_FOUND": "Node performance window not found.",
    "ERR_NOTIFICATION_NOT_FOUND": "Customer notification not found.",
    "ERR_STALE_ORDER_VERSION": "The supplied order version is stale.",
    "ERR_STALE_PICKUP_VERSION": "The supplied pickup version is stale.",
    "ERR_STALE_INVENTORY_VERSION": "The supplied inventory version is stale.",
    "ERR_ASSIGNMENT_STATE_INVALID": "The assignment is not in a state that allows this transition.",
    "ERR_ORDER_NOT_ROUTABLE": "The order is not routable in its current fulfillment status.",
    "ERR_ORDER_LINES_LOCKED": "Order lines are frozen once routing has begun.",
    "ERR_NO_ROUTABLE_LINES": "The order has no open units to route.",
    "ERR_ORDER_ALREADY_SHIPPED_UNITS": "The order already has shipped units.",
    "ERR_PICKUP_STATE_INVALID": "The carrier pickup is not in a state that allows this transition.",
    "ERR_STORE_NODE_DEACTIVATED": "The node is deactivated.",
    "ERR_STORE_NOT_DEACTIVATED": "The node is not deactivated.",
    "ERR_NO_OPEN_WINDOW": "No open performance window exists.",
    "ERR_SAFETY_STOCK_EXCEEDS_ON_HAND": "Safety stock may not exceed on-hand units.",
    "ERR_INVENTORY_BELOW_RESERVED": "The counted on-hand quantity is below the reserved quantity.",
    "ERR_STORE_CUTOFF_PASSED": "The node's same-day cutoff has passed.",
    "ERR_PICK_DEADLINE_PASSED": "The assignment's pick deadline has passed.",
    "ERR_PICKUP_WINDOW_CLOSED": "The carrier pickup window is not open at the current instant.",
    "ERR_INVALID_WINDOW": "window_end_utc must be strictly after window_start_utc.",
    "ERR_PICKUP_WINDOW_OVERLAP": "The proposed pickup window conflicts with an existing window.",
    "ERR_CLOCK_NOT_MONOTONIC": "The requested instant precedes the current clock.",
    "ERR_LABOR_WINDOW_OVERSUBSCRIBED": "Accepting this assignment would oversubscribe the node's pick labour.",
    "ERR_PICKUP_CAPACITY_EXCEEDED": "The carrier pickup has no remaining parcel capacity.",
    "ERR_PACKAGING_DEPLETED": "The node has no on-hand units of the requested packaging type.",
    "ERR_PACKAGE_TYPE_TOO_SMALL": "The chosen package type is smaller than the derived requirement.",
    "ERR_PICK_UNITS_INVALID": "The reported pick quantities are internally inconsistent.",
    "ERR_ZERO_PICK_NOT_ALLOWED": "A zero-unit pick is not allowed; reject the assignment instead.",
    "ERR_DUPLICATE_STORE_CODE": "store_code is already registered.",
    "ERR_DUPLICATE_SKU_CODE": "sku_code is already registered.",
    "ERR_DUPLICATE_ORDER_CODE": "order_code is already registered.",
    "ERR_DUPLICATE_INVENTORY_ROW": "An inventory row already exists for this store and sku.",
    "ERR_DUPLICATE_PACKAGING_ROW": "A packaging supply row already exists for this store and package type.",
    "ERR_PICKUP_STORE_MISMATCH": "The carrier pickup belongs to a different node.",
    "ERR_ASSIGNMENT_LINE_MISMATCH": "An assignment line does not belong to this assignment.",
    "ERR_PICKUP_HAS_PARCELS": "The carrier pickup already holds shipped parcels.",
    "ERR_COST_INDEX_GUARDRAIL": "The projected cost index exceeds the network guardrail.",
    "ERR_NOT_FOUND": "Resource not found.",
}
