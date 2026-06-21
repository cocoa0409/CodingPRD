"""Public serializers — strip private bookkeeping keys (those starting with '_').

The stored dicts already use the exact field names defined in SCAFFOLD 1.1, so
serialization is just a privacy filter (db.public). Kept as a module so call
sites read intentionally.
"""
import db


def ser(resource):
    return db.public(resource)
