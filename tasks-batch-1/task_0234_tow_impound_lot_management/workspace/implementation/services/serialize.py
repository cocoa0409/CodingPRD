"""Serialization: strip private (underscore-prefixed) fields from a record for
the response body. Computed fields are recomputed by the owning service before
serialization, so by the time we serialize the record's public fields are final."""


def public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}
