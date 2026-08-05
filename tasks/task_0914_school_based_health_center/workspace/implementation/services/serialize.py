"""Row -> JSON payload.

Rows are stored with exactly the field names the API exposes; anything
internal is prefixed with an underscore and stripped here.
"""


def dump(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def dump_all(rows):
    return [dump(r) for r in rows]


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset : offset + limit]
    return dump_all(window), total
