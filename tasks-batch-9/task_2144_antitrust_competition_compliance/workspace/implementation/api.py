"""Shared route helpers."""
from envelope import object_response, array_response
from ladder import commit
from store import sort_rows


def ok(row, ser):
    commit()
    return object_response(ser(row), 200)


def created(row, ser):
    commit()
    return object_response(ser(row), 201)


def plain(data, code=200):
    commit()
    return object_response(data, code)


def listing(items, ser, limit, offset):
    commit()
    ordered = sort_rows(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return array_response([ser(r) for r in page], limit, offset, total)
