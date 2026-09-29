"""Small shared helpers used by every route module."""

from envelope import ok, ok_list
from errors import ApiError
from validate import paginate


def get_or_404(mapping, row_id, error_id):
    row = mapping.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def listing(rows, serializer, paginated=True):
    if paginated:
        page, meta = paginate(rows)
        return ok_list([serializer(row) for row in page], meta)
    return ok_list([serializer(row) for row in rows])


def single(row, serializer, status=200):
    return ok(serializer(row), status)


def created(row, serializer):
    return ok(serializer(row), 201)
