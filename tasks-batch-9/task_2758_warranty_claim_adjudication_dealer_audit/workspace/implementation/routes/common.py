"""Helpers shared by the route modules."""

from decimal import Decimal

from flask import request

import db
import util
from errors import ApiError
from middleware import (
    ADJUDICATION_MANAGER,
    APPEAL_REVIEWER,
    AUDIT_MANAGER,
    CLAIM_ADJUDICATOR,
    DEALER_WARRANTY_ADMIN,
    FIELD_AUDITOR,
    WARRANTY_ADMIN,
)

ALL_ROLES = (
    WARRANTY_ADMIN,
    CLAIM_ADJUDICATOR,
    ADJUDICATION_MANAGER,
    FIELD_AUDITOR,
    AUDIT_MANAGER,
    APPEAL_REVIEWER,
    DEALER_WARRANTY_ADMIN,
)
MANUFACTURER_ROLES = (
    WARRANTY_ADMIN,
    CLAIM_ADJUDICATOR,
    ADJUDICATION_MANAGER,
    FIELD_AUDITOR,
    AUDIT_MANAGER,
    APPEAL_REVIEWER,
)


def resolve_fk(data, key, store, error_id):
    """Body foreign-key existence (ladder step 6), evaluated before body shape.

    An absent or non-string reference is left to the shape pass; a legible
    reference that names no live row fails immediately with the entity's code.
    """
    value = data.get(key)
    if not isinstance(value, str) or value.strip() == "":
        return None
    record = store.get(value)
    if record is None:
        raise ApiError(error_id)
    return record


def unique_or_reject(store, field, value):
    for record in store.values():
        if record.get(field) == value:
            util.bad("Field '%s' must be unique; '%s' is already registered." % (field, value))


def str_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def apply_filters(rows, specs):
    """specs: list of (filter_value, record_key)."""
    for value, key in specs:
        if value is None:
            continue
        rows = [row for row in rows if row.get(key) == value]
    return rows


def _scaled_is_integral(value, scale):
    return (value * Decimal(scale)) == (value * Decimal(scale)).to_integral_value()


def one_decimal(value, key):
    if value is None:
        return None
    if not _scaled_is_integral(value, 10):
        util.bad("Field '%s' must be carried to one decimal place." % key)
    return value


def two_decimals(value, key):
    if value is None:
        return None
    if not _scaled_is_integral(value, 100):
        util.bad("Field '%s' must be carried to two decimal places." % key)
    return value


def dealer_of_claim(claim):
    return db.dealers[claim["dealer_id"]]
