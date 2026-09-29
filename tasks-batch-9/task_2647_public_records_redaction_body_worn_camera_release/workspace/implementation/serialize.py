"""Entity serialization.

Rows are stored with exactly the fields the scaffold declares, so a generic
projection is sufficient; internal bookkeeping keys are prefixed with "_" and
are never exposed.
"""


def dump(row):
    if row is None:
        return None
    return {key: value for key, value in row.items() if not key.startswith("_")}


def dump_list(rows):
    return [dump(row) for row in rows]
