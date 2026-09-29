"""List-endpoint plumbing: pagination bounds, ordering and the array envelope."""

import response


def bounds():
    return response.pagination()


def respond(rows, serializer, limit, offset, sort_key=None):
    ordered = list(rows)
    if sort_key is not None:
        ordered.sort(key=sort_key)
    page, total = response.paginate(ordered, limit, offset)
    return response.list_response([serializer(r) for r in page], limit, offset, total)


def by_created_at(row):
    return (row["created_at"], row["_seq"])
