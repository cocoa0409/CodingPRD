"""Serialization: strip internal bookkeeping fields before returning records.
Records are stored as plain dicts already holding their public fields; we only
remove the leading-underscore internal keys."""


def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
