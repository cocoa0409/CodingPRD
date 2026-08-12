"""Error catalogue (§1.6 / PRD §5) and the exception type that carries it."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    # auth / authz
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_ORDER_OWNER": 403,
    "ERR_NOT_DROP_COORDINATOR": 403,
    # existence
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_DROP_POINT_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_PRICE_VERSION_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_ROUTE_RUN_NOT_FOUND": 404,
    "ERR_DROP_RUN_NOT_FOUND": 404,
    "ERR_MEMBER_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_CASE_AGGREGATE_NOT_FOUND": 404,
    "ERR_RECEIPT_LINE_NOT_FOUND": 404,
    "ERR_SUBSTITUTION_OFFER_NOT_FOUND": 404,
    "ERR_PALLET_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_RECONCILIATION_NOT_FOUND": 404,
    "ERR_COMMISSION_ACCRUAL_NOT_FOUND": 404,
    "ERR_VOLUNTEER_SHIFT_NOT_FOUND": 404,
    "ERR_CREDIT_GRANT_NOT_FOUND": 404,
    # request shape
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_QUANTITY": 422,
    # write gates
    "ERR_CYCLE_CLOSED": 409,
    "ERR_MEMBERSHIP_LAPSED": 403,
    "ERR_COORDINATOR_INELIGIBLE": 403,
    "ERR_RECONCILIATION_POSTED": 409,
    "ERR_CYCLE_LOCKED": 409,
    # state
    "ERR_INVALID_CYCLE_STATE": 409,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_LINE_STATE": 409,
    "ERR_INVALID_DROP_RUN_STATE": 409,
    "ERR_INVALID_ROUTE_RUN_STATE": 409,
    "ERR_INVALID_OFFER_STATE": 409,
    "ERR_INVALID_RECONCILIATION_STATE": 409,
    "ERR_INVALID_ACCRUAL_STATE": 409,
    "ERR_INVALID_SHIFT_STATE": 409,
    "ERR_INVALID_PALLET_STATE": 409,
    "ERR_STALE_VERSION": 412,
    # temporal
    "ERR_CUTOFF_PASSED": 409,
    "ERR_EXCEPTION_WINDOW_CLOSED": 409,
    "ERR_EXCEPTION_WINDOW_OPEN": 409,
    "ERR_PRICE_VERSION_OVERLAP": 409,
    "ERR_ROUTE_WINDOW_CONFLICT": 409,
    # constraint satisfaction
    "ERR_ROUTE_NO_COLD_CHAIN": 422,
    "ERR_REEFER_CAPACITY_EXCEEDED": 409,
    "ERR_PALLET_CAPACITY_EXCEEDED": 409,
    "ERR_ITEM_DISCONTINUED": 409,
    "ERR_NO_EFFECTIVE_PRICE": 409,
    "ERR_DUPLICATE_LINE_FOR_ITEM": 409,
    "ERR_DUPLICATE_ORDER_FOR_MEMBER": 409,
    "ERR_MERGE_TARGET_INVALID": 422,
    "ERR_ROLLFORWARD_LIMIT": 409,
    "ERR_RECEIPT_EXCEEDS_ORDERED": 422,
    "ERR_PALLETS_NOT_SEALED": 409,
    "ERR_SUPPLIER_INVOICE_MISSING": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VARIANCE_UNRESOLVED": 422,
    # fiscal
    "ERR_ROUTE_MINIMUM_NOT_MET": 409,
    "ERR_DROP_RECONCILIATION_INCOMPLETE": 409,
    "ERR_CREDIT_CAP_EXCEEDED": 422,
    "ERR_PAYMENT_VARIANCE_EXCEEDED": 409,
    "ERR_REFUND_EXCEEDS_CAPTURE": 422,
    "ERR_VOLUNTEER_OBLIGATION_UNMET": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role must both be present and name a known role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_ORDER_OWNER": "The acting member does not own this order.",
    "ERR_NOT_DROP_COORDINATOR": "The acting member is not this drop run's coordinator.",
    "ERR_VALIDATION": "The request payload is invalid.",
    "ERR_INVALID_ENUM": "An enum-typed field carries a value outside its declared member list.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in [1, 100] and offset an integer >= 0.",
    "ERR_INVALID_QUANTITY": "qty_units is out of range or violates the whole-case rule.",
    "ERR_CYCLE_CLOSED": "The cycle this target resolves to is CLOSED.",
    "ERR_MEMBERSHIP_LAPSED": "The member in scope has status LAPSED.",
    "ERR_COORDINATOR_INELIGIBLE": "The acting coordinator's tier_rank is below 2.",
    "ERR_RECONCILIATION_POSTED": "The drop run already carries a POSTED reconciliation.",
    "ERR_CYCLE_LOCKED": "The parent cycle is no longer OPEN.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the stored version.",
}


def _default_not_found(name):
    return "%s does not resolve to a stored row." % name


for _eid, _http in ERROR_HTTP.items():
    if _http == 404 and _eid not in DEFAULT_MESSAGES:
        DEFAULT_MESSAGES[_eid] = _default_not_found(_eid)
    DEFAULT_MESSAGES.setdefault(_eid, _eid)
