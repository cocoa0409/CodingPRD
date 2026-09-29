"""Shared route helpers: bodies, natural keys and licence fitness checks."""

from flask import request

from db import db, touch
from errors import ApiError

STATUS_OK = 200
STATUS_CREATED = 201


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return payload


def unique(collection, field_name, value):
    """Band 12 (V-CON-5): natural-key uniqueness."""
    for row in getattr(db, collection).values():
        if row.get(field_name) == value:
            raise ApiError("ERR_DUPLICATE_CODE")


def license_term_check(license_row, instant):
    """Band 13 (V-TEMP-4): lazy expiry against the logical clock.

    PRD 3.2 ties the lazy status flip to the *clock*: "When run scheduling, run
    starting, or the start of SKU testing consults a grant that is ACTIVE and
    finds the clock at or past its valid_until, the grant's status is first set
    to EXPIRED and its version advanced".  `instant` is therefore always the
    logical clock here.
    """
    if instant >= license_row["valid_until"] or instant < license_row["valid_from"]:
        if license_row["status"] == "ACTIVE":
            license_row["status"] = "EXPIRED"
            touch(license_row)
        raise ApiError("ERR_LICENSE_EXPIRED")


def license_window_check(license_row, instant):
    """Band 13: a requested window instant outside the grant's term.

    PRD 3.2: "The same code and status apply when a run is scheduled with a
    `planned_start_utc` at or after `valid_until`, or strictly earlier than
    `valid_from`."  This reading of the term is not the lazy-expiry trigger --
    only the clock flips the grant -- so no status is rewritten here.
    """
    if instant >= license_row["valid_until"] or instant < license_row["valid_from"]:
        raise ApiError("ERR_LICENSE_EXPIRED")


def license_active_check(license_row):
    """Band 14 (V-REF-4)."""
    if license_row is None or license_row["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE")


def film_available_check(film):
    """Band 14 (V-REF-3)."""
    if film is None or film["status"] != "AVAILABLE":
        raise ApiError("ERR_PRINT_FILM_NOT_AVAILABLE")
