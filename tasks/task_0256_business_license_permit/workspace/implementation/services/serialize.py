"""Output projection for each entity. Returns the stored dict as-is (it already holds
exactly the declared fields). Kept as a seam in case projection ever needs to differ
from storage."""


def public(record):
    return dict(record)


def public_list(records):
    return [dict(r) for r in records]
