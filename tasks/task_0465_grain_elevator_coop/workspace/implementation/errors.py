"""Error catalog. Error IDs and HTTP statuses come verbatim from PRD §5 / SCAFFOLD errors."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Universal gates (PRD §2.6 ordering) ---
def unauthenticated(msg="Authentication required: X-User-Role missing or unknown."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role is not permitted to perform this operation."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Request body is missing, ill-typed, or violates a field constraint."):
    return ApiError("ERR_INVALID_REQUEST", 422, msg)


def invalid_state(msg="Resource is not in a state from which this transition is defined."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def commodity_mismatch(msg="Contract and storage position do not share commodity_id and member_id."):
    return ApiError("ERR_COMMODITY_MISMATCH", 409, msg)


def leg_already_fixed(msg="The requested leg is already fixed for this contract_type."):
    return ApiError("ERR_LEG_ALREADY_FIXED", 409, msg)


def no_current_price(msg="No current PriceBoard exists for the commodity."):
    return ApiError("ERR_NO_CURRENT_PRICE", 409, msg)


def contract_not_priced(msg="Settlement post requires the contract priced."):
    return ApiError("ERR_CONTRACT_NOT_PRICED", 409, msg)


def contract_overfill(msg="Settlement priced_bushels exceeds the contract's remaining unfilled bushels."):
    return ApiError("ERR_CONTRACT_OVERFILL", 409, msg)


def insufficient_bushels(msg="Drawn bushels exceed the storage position's bushels_available."):
    return ApiError("ERR_INSUFFICIENT_BUSHELS", 409, msg)


def program_mismatch(msg="Operation requires a DELAYED_PRICE position."):
    return ApiError("ERR_PROGRAM_MISMATCH", 409, msg)


def margin_call_unmet(msg="Deposit does not cover the outstanding margin call."):
    return ApiError("ERR_MARGIN_CALL_UNMET", 409, msg)


def contract_has_settlements(msg="Contract has applied settlement bushels and cannot be cancelled."):
    return ApiError("ERR_CONTRACT_HAS_SETTLEMENTS", 409, msg)


def empty_patronage_pool(msg="Patronage close requires total net_priced_bushels > 0."):
    return ApiError("ERR_EMPTY_PATRONAGE_POOL", 409, msg)


def resource_window_conflict(msg="The requested window conflicts with an existing reservation on the same resource."):
    return ApiError("ERR_RESOURCE_WINDOW_CONFLICT", 409, msg)


def stale_version(msg="The expected version does not match the resource's current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)
