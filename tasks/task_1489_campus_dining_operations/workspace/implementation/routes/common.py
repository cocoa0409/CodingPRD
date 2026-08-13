"""Shared list-endpoint helper: auth (any role), filters, pagination, envelope."""
from flask import request

from db import DB
from middleware import ALL_ROLES, auth
from response import ok_list
from services import ser, sorted_created
from util import pagination_args


def list_endpoint(store, filters):
    """filters: list of (query_param, record_key) exact-match filters."""
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = sorted_created(DB[store].values())
    for param, key in filters:
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if str(r.get(key)) == val]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser(r) for r in page], total, limit, offset)
