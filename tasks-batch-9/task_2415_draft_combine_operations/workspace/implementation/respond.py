"""Handler exit points: settle version bumps, then project the response."""

import response
import serialize
import versioning


def ok(rec):
    versioning.commit()
    return response.obj(serialize.serialize(rec))


def created(rec):
    versioning.commit()
    return response.created(serialize.serialize(rec))


def payload(data):
    versioning.commit()
    return response.obj(data)


def one(rec):
    """Read-only single-resource projection; no version settlement."""
    return response.obj(serialize.serialize(rec))


def listing(records, limit, offset):
    total = len(records)
    window = records[offset : offset + limit]
    return response.collection(serialize.serialize_many(window), limit, offset, total)
