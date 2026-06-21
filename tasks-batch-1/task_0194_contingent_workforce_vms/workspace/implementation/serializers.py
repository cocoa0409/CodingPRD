"""Public serialization of records: strips internal-only keys (those starting with '_')."""


def public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}
