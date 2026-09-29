"""Shared guards for the rejection ladder of PRD 2.8."""

from errors import ApiError
from store import store
from validation import bool_filter, filters, pagination

# path / body identifier -> 404 error id (PRD 2.8)
NOT_FOUND = {
    "variety_id": "ERR_VARIETY_NOT_FOUND",
    "filing_id": "ERR_PROTECTION_FILING_NOT_FOUND",
    "trial_site_id": "ERR_TRIAL_SITE_NOT_FOUND",
    "trial_id": "ERR_VARIETY_TRIAL_NOT_FOUND",
    "propagator_id": "ERR_PROPAGATOR_NOT_FOUND",
    "suspected_propagator_id": "ERR_PROPAGATOR_NOT_FOUND",
    "agreement_id": "ERR_AGREEMENT_NOT_FOUND",
    "quota_id": "ERR_QUOTA_NOT_FOUND",
    "tag_order_id": "ERR_TAG_ORDER_NOT_FOUND",
    "report_id": "ERR_ROYALTY_REPORT_NOT_FOUND",
    "royalty_report_id": "ERR_ROYALTY_REPORT_NOT_FOUND",
    "line_item_id": "ERR_LINE_ITEM_NOT_FOUND",
    "grant_id": "ERR_SUBLICENSE_GRANT_NOT_FOUND",
    "case_id": "ERR_SURVEILLANCE_CASE_NOT_FOUND",
    "test_id": "ERR_GENETIC_TEST_NOT_FOUND",
    "engagement_id": "ERR_AUDIT_ENGAGEMENT_NOT_FOUND",
}

COLLECTION_FOR = {
    "variety_id": "varieties",
    "filing_id": "filings",
    "trial_site_id": "trial_sites",
    "trial_id": "trials",
    "propagator_id": "propagators",
    "suspected_propagator_id": "propagators",
    "agreement_id": "agreements",
    "quota_id": "quotas",
    "tag_order_id": "tag_orders",
    "report_id": "reports",
    "royalty_report_id": "reports",
    "line_item_id": "line_items",
    "grant_id": "grants",
    "case_id": "cases",
    "test_id": "tests",
    "engagement_id": "engagements",
}


def resolve(identifier_name, value):
    """Resolve one identifier, raising that entity's own 404 code."""
    collection = getattr(store, COLLECTION_FOR[identifier_name])
    record = collection.get(value) if isinstance(value, str) else None
    if record is None:
        raise ApiError(NOT_FOUND[identifier_name])
    return record


def terminal(condition):
    if condition:
        raise ApiError("ERR_TERMINAL_STATE")


def transition(condition):
    """`condition` is True when the current state IS a declared origin state."""
    if not condition:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")


def require_quota_not_frozen(quota):
    if quota["status"] == "FROZEN":
        raise ApiError("ERR_QUOTA_FROZEN")


def require_agreement_active(agreement):
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")


def require_owner(actor, propagator_id):
    if actor.user_id != propagator_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_distinct_actor(actor, recorded_user_id):
    if recorded_user_id is not None and actor.user_id == recorded_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


def check_occ(body, field, record, error_id):
    if int(body[field]) != int(record["version"]):
        raise ApiError(error_id)


def agreement_of_report(report):
    return store.agreements[report["agreement_id"]]


def propagator_of_agreement(agreement):
    return store.propagators[agreement["propagator_id"]]


def paged(records):
    limit, offset = pagination()
    total = len(records)
    return records[offset:offset + limit], limit, offset, total


BOOL_FILTERS = ("overrun_flagged",)


def filtered(collection, *filter_names):
    """Equality filters, created_at ascending, then offset/limit paging."""
    wanted = filters(*filter_names)
    records = store.ordered(collection)
    for name, raw in wanted.items():
        if name in BOOL_FILTERS:
            value = bool_filter(raw)
        else:
            value = raw
        records = [r for r in records if r.get(name) == value]
    return paged(records)
