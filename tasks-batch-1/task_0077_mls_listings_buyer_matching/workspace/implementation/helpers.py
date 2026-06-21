"""Shared route helpers: body parsing, lookups, common validators."""
from flask import request

from db import db
from errors import err


def body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err("ERR_VALIDATION", f"Missing required field: {f}")


def get_or_404(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def require_int(data, key, required=True, default=None, min_value=None):
    if key not in data or data[key] is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {key}")
        return default
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", f"{key} must be an integer")
    if min_value is not None and val < min_value:
        raise err("ERR_VALIDATION", f"{key} below minimum")
    return val


def require_number(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {key}")
        return default
    val = data[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_VALIDATION", f"{key} must be a number")
    return val


def require_str(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {key}")
        return default
    val = data[key]
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"{key} must be a string")
    return val


def listing_of_lockbox(lockbox):
    return db.listings.get(lockbox["listing_id"])


def listing_of_showing(showing):
    lb = db.lockboxes.get(showing["lockbox_id"])
    if lb is None:
        return None
    return db.listings.get(lb["listing_id"])


def listing_of_offer(offer):
    return db.listings.get(offer["listing_id"])
