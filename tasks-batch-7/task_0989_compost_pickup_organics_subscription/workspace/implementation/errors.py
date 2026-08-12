"""Error classes and error ID constants (PRD section 5 catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                    # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                      # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"        # 403
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                    # 400
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                # 404
ERR_STALE_VERSION = "ERR_STALE_VERSION"                        # 412
ERR_SUBSCRIPTION_STATE_CONFLICT = "ERR_SUBSCRIPTION_STATE_CONFLICT"  # 409
ERR_SUBSCRIPTION_NOT_ACTIVE = "ERR_SUBSCRIPTION_NOT_ACTIVE"    # 409
ERR_PICKUP_NOT_ACTIONABLE = "ERR_PICKUP_NOT_ACTIONABLE"        # 409
ERR_TAG_NOT_RESOLVABLE = "ERR_TAG_NOT_RESOLVABLE"              # 409
ERR_REDEMPTION_NOT_FULFILLABLE = "ERR_REDEMPTION_NOT_FULFILLABLE"  # 409
ERR_INVOICE_NOT_PAYABLE = "ERR_INVOICE_NOT_PAYABLE"            # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                        # 409
ERR_ACCOUNT_DELINQUENT = "ERR_ACCOUNT_DELINQUENT"              # 402
ERR_INSUFFICIENT_CREDIT = "ERR_INSUFFICIENT_CREDIT"            # 422
ERR_SKIP_LIMIT_EXCEEDED = "ERR_SKIP_LIMIT_EXCEEDED"            # 422
ERR_ROUTE_CAPACITY = "ERR_ROUTE_CAPACITY"                      # 422
ERR_NO_BIN_AVAILABLE = "ERR_NO_BIN_AVAILABLE"                  # 422
ERR_PLAN_DOWNGRADE_BLOCKED = "ERR_PLAN_DOWNGRADE_BLOCKED"      # 422
ERR_TAG_ALREADY_OPEN = "ERR_TAG_ALREADY_OPEN"                  # 409
ERR_DUPLICATE_WEIGH_TICKET = "ERR_DUPLICATE_WEIGH_TICKET"      # 409
ERR_INVALID_WEIGHT = "ERR_INVALID_WEIGHT"                      # 422
ERR_PICKUP_LOCKED_BY_WEIGH_TICKET = "ERR_PICKUP_LOCKED_BY_WEIGH_TICKET"  # 409
ERR_SKIP_CUTOFF_PASSED = "ERR_SKIP_CUTOFF_PASSED"              # 422
ERR_PAUSE_WINDOW_OVERLAP = "ERR_PAUSE_WINDOW_OVERLAP"          # 422
ERR_SERVICE_DATE_WEEKDAY_MISMATCH = "ERR_SERVICE_DATE_WEEKDAY_MISMATCH"  # 422
ERR_WEIGH_TICKET_PENDING = "ERR_WEIGH_TICKET_PENDING"          # 422
# Stock gate named in PRD 3.8 / calculations.compost_stock (absent from the
# section-5 catalogue); treated as a 422 availability constraint.
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"              # 422


def bad_request(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def not_found(msg="Resource not found"):
    raise ApiError(ERR_NOT_FOUND, 404, msg)


def forbidden(msg="Role not allowed or resource not owned by caller"):
    raise ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def conflict(error_id, msg):
    raise ApiError(error_id, 409, msg)


def unprocessable(error_id, msg):
    raise ApiError(error_id, 422, msg)
