"""Shared route helpers: list pagination, single-resource reads, serializers."""
from flask import request

from middleware import ANY_ROLE, authorized
from response import success_list, success_object
from services.calculations import seats_taken
from services.core import public, sorted_all
from validate import get_pagination, require_path_resource


def list_response(collection, filters=None, serializer=public):
    """List endpoints: any declared role; priority-4 pagination; created_at ASC."""
    authorized(ANY_ROLE)
    limit, offset = get_pagination()
    items = sorted_all(collection)
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


def get_one(collection, rid, serializer=public):
    authorized(ANY_ROLE)
    rec = require_path_resource(collection, rid)
    return success_object(serializer(rec))


def serialize_offering(offering):
    """CourseOffering with the computed seat ledger fields (seat_availability)."""
    out = public(offering)
    taken = seats_taken(offering["id"])
    out["seats_taken"] = taken
    out["seats_available"] = offering["capacity"] - taken
    return out


def arg(name):
    return request.args.get(name)
