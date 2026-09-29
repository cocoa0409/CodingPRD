"""Helpers shared by the route modules."""

from flask import request

from db import db, serialize, sorted_records
from errors import ApiError
from response import ok_list
from validation import pagination

# path-identifier 404s (PRD 2.8)
NOT_FOUND = {
    "search_rings": "ERR_SEARCH_RING_NOT_FOUND",
    "candidates": "ERR_CANDIDATE_NOT_FOUND",
    "landlords": "ERR_LANDLORD_NOT_FOUND",
    "jurisdictions": "ERR_JURISDICTION_NOT_FOUND",
    "leases": "ERR_LEASE_NOT_FOUND",
    "zoning_applications": "ERR_ZONING_APPLICATION_NOT_FOUND",
    "structural_analyses": "ERR_STRUCTURAL_ANALYSIS_NOT_FOUND",
    "modification_designs": "ERR_MODIFICATION_DESIGN_NOT_FOUND",
    "environmental_reviews": "ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND",
    "construction_permits": "ERR_PERMIT_NOT_FOUND",
    "utility_providers": "ERR_UTILITY_PROVIDER_NOT_FOUND",
    "backhaul_orders": "ERR_BACKHAUL_ORDER_NOT_FOUND",
    "on_air_plans": "ERR_ON_AIR_PLAN_NOT_FOUND",
}


def fetch(collection_name, record_id):
    collection = getattr(db, collection_name)
    record = collection.get(record_id)
    if record is None:
        raise ApiError(NOT_FOUND[collection_name], 404)
    return record


def paginated(records, serializer=serialize):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def listing(collection_name, filters):
    """Standard list endpoint: filters, created_at ascending, offset/limit."""
    limit, offset = pagination()
    records = sorted_records(getattr(db, collection_name))
    for field in filters:
        wanted = request.args.get(field)
        if wanted is None:
            continue
        records = [r for r in records if _matches(r.get(field), wanted)]
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, total)


def _matches(value, wanted):
    if value is None:
        return wanted in ("", "null")
    return str(value) == wanted
