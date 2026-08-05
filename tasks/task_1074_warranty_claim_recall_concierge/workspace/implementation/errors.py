"""Error class and error-id -> (http, default message) catalog."""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Missing or malformed authentication headers."),
    "ERR_UNAUTHORIZED": (403, "The acting role is not permitted for this operation."),
    "ERR_NOT_HOUSEHOLD_MEMBER": (403, "The acting user is not a member of the resource's household."),
    "ERR_NOT_FOUND": (404, "A referenced resource does not exist."),
    "ERR_INVALID_REQUEST": (400, "The request body is malformed."),
    "ERR_INVALID_STATE": (409, "The requested transition is not defined from the current state."),
    "ERR_PRODUCT_ARCHIVED": (409, "The product is archived."),
    "ERR_PRODUCT_HAS_ACTIVE_CLAIM": (409, "The product has a non-terminal claim."),
    "ERR_RECALL_NOT_LIVE": (409, "The parent recall notice is not published."),
    "ERR_RECALL_WINDOW_OVERLAP": (409, "The recall window overlaps an existing published recall."),
    "ERR_SUBSCRIPTION_PERIOD_OVERLAP": (409, "The subscription period overlaps an existing subscription."),
    "ERR_SUBSCRIPTION_NOT_ACTIVE": (409, "The household's subscription is not active."),
    "ERR_MISSING_DOCUMENTATION": (409, "No qualifying claim documentation exists."),
    "ERR_CLAIM_ALLOWANCE_EXCEEDED": (409, "The subscription claim allowance is exhausted."),
    "ERR_SEGREGATION_OF_DUTIES": (409, "The reviewer may not also decide the claim."),
    "ERR_COORDINATION_DISABLED": (409, "The manufacturer does not participate in RMA coordination."),
    "ERR_RMA_NOT_AUTHORIZED": (409, "The replacement requires an authorized RMA before dispatch."),
    "ERR_STALE_VERSION": (412, "The expected subscription version does not match."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        default_http, default_msg = ERROR_CATALOG.get(error_id, (400, "Error."))
        self.http_status = http_status if http_status is not None else default_http
        self.message = message if message is not None else default_msg
        super().__init__(self.message)
