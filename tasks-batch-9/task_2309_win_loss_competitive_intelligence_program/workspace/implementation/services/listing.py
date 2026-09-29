"""List ordering helpers (PRD 2.3). No collection is ever ordered by id."""


def by_created_at(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def by_key(rows, key):
    return sorted(rows, key=key)


def epoch(dt):
    return dt.timestamp()
