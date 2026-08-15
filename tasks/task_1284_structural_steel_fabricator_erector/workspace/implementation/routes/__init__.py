"""Route blueprints and a shared filtered/paginated list helper."""

from envelope import ok_list
from store import sorted_records
from validate import pagination_params


def list_response(records, view, filters):
    """filters: list of (query_param, record_field) exact-match filters."""
    from flask import request

    items = sorted_records(list(records))
    for param, field in filters:
        raw = request.args.get(param)
        if raw is not None:
            items = [r for r in items if str(r.get(field)) == raw]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([view(r) for r in page], limit, offset, total)


from . import (  # noqa: E402,F401
    backcharges,
    billings,
    clock,
    drawings,
    fixes,
    inspections,
    jobs,
    loads,
    mill_orders,
    pieces,
    sequences,
    welders,
    welds,
)
