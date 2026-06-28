"""Shared route helpers: ownership checks, list/sort/paginate."""
from flask import request

from errors import err
from response import array_response
from state import store
from validation import parse_pagination, paginate


def sort_by_created(items):
    """Sort by created_at ascending (oldest first), tie-broken by insertion seq."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def list_response(items, serializer):
    """Sort by created_at, paginate per query params, serialize, and envelope."""
    limit, offset = parse_pagination()
    ordered = sort_by_created(items)
    page, total = paginate(ordered, limit, offset)
    data = [serializer(store, e) for e in page]
    return array_response(store.clock, data, limit, offset, total)


def member_owns(user_id, member_id):
    """Member-role ownership check (PRD §2.1)."""
    return user_id == member_id


def query_filter(args, field):
    """Return the raw query string value for `field`, or None."""
    return args.get(field)
