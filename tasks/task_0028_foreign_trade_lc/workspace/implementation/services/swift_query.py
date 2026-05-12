"""SWIFT message read endpoints."""

import db
from errors import raise_error, ERR_NOT_FOUND


def get_message(message_id):
    m = db.get_by_id("swift_messages", message_id)
    if m is None:
        raise_error(ERR_NOT_FOUND, "swift message not found")
    return m


def list_lc_messages(lc_id, filters, limit, offset):
    lc = db.get_by_id("letters_of_credit", lc_id)
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    use_filters = {"lc_id": lc_id}
    if filters and filters.get("message_type"):
        use_filters["message_type"] = filters["message_type"]
    rows, total = db.list_table("swift_messages", filters=use_filters,
                                sort_keys=("created_at", "id"), limit=limit, offset=offset)
    return rows, total
