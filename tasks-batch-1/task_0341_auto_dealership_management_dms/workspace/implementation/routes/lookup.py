"""Resource resolution helpers.

Path identifiers that do not resolve => ERR_NOT_FOUND (404).
Body foreign keys that do not resolve => ERR_FK_NOT_FOUND (404).
"""
import db
from errors import err


def get_path(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def get_fk(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced resource not found")
    return rec
