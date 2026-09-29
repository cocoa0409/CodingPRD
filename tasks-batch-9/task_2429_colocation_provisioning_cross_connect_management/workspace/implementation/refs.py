"""Path and body reference resolution — PRD §2.5 rules 3 and 4, §2.10.

Path identifiers resolve left to right and the first unresolved identifier
decides the 404 code. Body references resolve in the order the fields are
declared for the target entity, before any business rule runs.
"""

from errors import ApiError
from store import store

CUSTOMER = ("customers", "ERR_CUSTOMER_NOT_FOUND")
CONTRACT = ("contracts", "ERR_CONTRACT_NOT_FOUND")
ROW = ("rows", "ERR_ROW_NOT_FOUND")
CABINET = ("cabinets", "ERR_CABINET_NOT_FOUND")
CIRCUIT = ("circuits", "ERR_CIRCUIT_NOT_FOUND")
PORT = ("ports", "ERR_PORT_NOT_FOUND")
CC_ORDER = ("cc_orders", "ERR_CROSS_CONNECT_ORDER_NOT_FOUND")
TICKET = ("tickets", "ERR_TICKET_NOT_FOUND")
CONTACT = ("contacts", "ERR_CONTACT_NOT_FOUND")
VISIT = ("visits", "ERR_VISIT_NOT_FOUND")
DECOM = ("decoms", "ERR_DECOMMISSION_ORDER_NOT_FOUND")
INVOICE_LINE = ("invoice_lines", "ERR_INVOICE_LINE_NOT_FOUND")


def _collection(kind):
    return getattr(store, kind[0])


def path_row(kind, identifier):
    row = _collection(kind).get(identifier)
    if row is None:
        raise ApiError(kind[1], "no such resource: %s" % identifier)
    return row


def body_fk(body, name, kind):
    """Resolve one declared body reference. A field that is absent or null is
    left to the required-field validation of rule 11."""
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or value not in _collection(kind):
        raise ApiError(kind[1], "%s does not reference a stored row" % name)
    return _collection(kind)[value]
