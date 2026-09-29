"""Error catalogue (PRD 5) as a single exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super(ApiError, self).__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(detail="Authentication headers missing or role unrecognized"):
    return ApiError("ERR_UNAUTHENTICATED", 401, detail)


def role_not_permitted(role, method, path):
    return ApiError("ERR_ROLE_NOT_PERMITTED", 403,
                    "Role %s may not call %s %s" % (role, method, path))


def dealer_scope(actor_id, dealer_id):
    return ApiError("ERR_DEALER_SCOPE_VIOLATION", 403,
                    "Dealer %s may not act on records belonging to dealer %s"
                    % (actor_id, dealer_id))


def invalid(detail):
    return ApiError("ERR_INVALID_REQUEST", 400, "Invalid request: %s" % detail)


def model_not_found(model_id):
    return ApiError("ERR_MODEL_NOT_FOUND", 404, "Trailer model %s not found" % model_id)


def dealer_not_found(dealer_id):
    return ApiError("ERR_DEALER_NOT_FOUND", 404, "Dealer %s not found" % dealer_id)


def unit_not_found(unit_id):
    return ApiError("ERR_UNIT_NOT_FOUND", 404, "Trailer unit %s not found" % unit_id)


def order_not_found(order_id):
    return ApiError("ERR_ORDER_NOT_FOUND", 404, "Dealer order %s not found" % order_id)


def claim_not_found(claim_id):
    return ApiError("ERR_CLAIM_NOT_FOUND", 404, "Warranty claim %s not found" % claim_id)


def resource_not_found(kind, resource_id):
    return ApiError("ERR_RESOURCE_NOT_FOUND", 404, "%s %s not found" % (kind, resource_id))


def duplicate_code(field, value):
    return ApiError("ERR_DUPLICATE_CODE", 409, "%s %s is already in use" % (field, value))
