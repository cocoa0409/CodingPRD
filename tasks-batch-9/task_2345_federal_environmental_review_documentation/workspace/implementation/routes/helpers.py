"""Shared lookup and listing helpers used by every route module."""

import db
import response
import validation as v
from errors import ApiError


def path_row(table, row_id, label):
    """Band 4: path identifiers resolve left to right, failing with 404."""
    row = db.find(table, row_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "%s not found" % label, 404)
    return row


def body_ref(table, row_id, label):
    """Band 5: body foreign keys fail with ERR_REFERENCE_NOT_FOUND."""
    row = db.find(table, row_id)
    if row is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "%s does not resolve" % label, 404)
    return row


def office_of(action):
    return db.find("offices", action["office_id"])


def list_response(items, *filter_names):
    limit, offset = v.pagination()
    items = v.apply_filters(items, v.filters(*filter_names))
    page, total = response.paginate(items, limit, offset)
    return response.listing(db.public_list(page), limit, offset, total)


def of_action(table, action_id):
    return [row for row in db.rows(table) if row["action_id"] == action_id]
