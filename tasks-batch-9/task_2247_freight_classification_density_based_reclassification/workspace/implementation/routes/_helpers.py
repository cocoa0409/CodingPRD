"""Shared route plumbing: list pagination, filters and shipper read scoping."""
import auth
import db
import response
import validation


def paged(rows, serializer):
    limit, offset = validation.pagination()
    total = len(rows)
    page = rows[offset : offset + limit]
    return response.collection([serializer(row) for row in page], limit, offset, total)


def apply_filters(rows, spec):
    """spec: iterable of (query_param, row_field, allowed_values_or_None)."""
    for param, field, allowed in spec:
        value = validation.query_filter(param, allowed)
        if value is None:
            continue
        rows = [row for row in rows if _matches(row.get(field), value)]
    return rows


def _matches(actual, wanted):
    if actual is None:
        return False
    if isinstance(actual, bool):
        return str(actual).lower() == wanted.lower()
    return str(actual) == wanted


def shipper_scope(rows, field):
    """Shipper list reads only ever see their own rows."""
    if auth.is_shipper():
        me = auth.user_id()
        return [row for row in rows if row.get(field) == me]
    return rows


def shipment_of(row):
    return db.get("shipments", row.get("shipment_id"))


def require_shipper_read(customer_id):
    if auth.is_shipper():
        auth.require_owner(customer_id)
