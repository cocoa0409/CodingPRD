"""Convert internal records into clean API output objects.

Internal records carry private keys (prefixed with '_') that must never be
exposed in responses.
"""


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]
