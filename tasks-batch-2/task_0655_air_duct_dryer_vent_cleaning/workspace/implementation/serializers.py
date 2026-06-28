"""Serialize records for API output: strip internal fields (those prefixed _)."""


def public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
