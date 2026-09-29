"""Path and body reference resolution (PRD 2.8). Each family has its own
not-found error, and multi-segment paths resolve strictly left to right."""

from core import ApiError, store


def _find(bucket, identifier, error_id):
    record = bucket.get(identifier) if isinstance(identifier, str) else None
    if record is None:
        raise ApiError(error_id)
    return record


def vendor(identifier):
    return _find(store.vendors, identifier, "ERR_VENDOR_NOT_FOUND")


def guide(identifier):
    return _find(store.guides, identifier, "ERR_ROUTING_GUIDE_NOT_FOUND")


def requirement(identifier):
    return _find(store.requirements, identifier, "ERR_REQUIREMENT_NOT_FOUND")


def purchase_order(identifier):
    return _find(store.purchase_orders, identifier, "ERR_PURCHASE_ORDER_NOT_FOUND")


def shipment(identifier):
    return _find(store.shipments, identifier, "ERR_SHIPMENT_NOT_FOUND")


def violation(identifier):
    return _find(store.violations, identifier, "ERR_VIOLATION_NOT_FOUND")


def chargeback(identifier):
    return _find(store.chargebacks, identifier, "ERR_CHARGEBACK_NOT_FOUND")


def dispute(identifier):
    return _find(store.disputes, identifier, "ERR_DISPUTE_NOT_FOUND")


def scorecard(identifier):
    return _find(store.scorecards, identifier, "ERR_SCORECARD_NOT_FOUND")


def cap(identifier):
    return _find(store.caps, identifier, "ERR_CAP_NOT_FOUND")


def deduction(identifier):
    return _find(store.deductions, identifier, "ERR_DEDUCTION_NOT_FOUND")


def allocation(identifier):
    return _find(store.allocations, identifier, "ERR_ALLOCATION_NOT_FOUND")
