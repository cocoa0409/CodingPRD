"""Shared list-endpoint plumbing: §2.3 pagination plus the optional equality
filters named in the endpoint table of §4.
"""

from core import ordered, paginate, pagination, query_filter, respond_list


def list_response(rows, fields, serializer):
    limit, offset = pagination()
    rows = ordered(rows)
    for field in fields:
        rows = query_filter(rows, field)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializer(row) for row in page], limit, offset, total)
