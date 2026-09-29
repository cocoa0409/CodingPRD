"""Existence lookups (ladder rungs 5-15).

`fetch_*` raises the collection's not-found error. `maybe_*` raises it only when a
client actually supplied an identifier, so an absent body field falls through to
rung 16 (ERR_INVALID_REQUEST) instead of reporting a phantom 404.
"""

import store
from errors import fail

_SPEC = {
    "memberships": "ERR_MEMBERSHIP_NOT_FOUND",
    "membership_tiers": "ERR_TIER_NOT_FOUND",
    "members": "ERR_MEMBER_NOT_FOUND",
    "parks": "ERR_PARK_NOT_FOUND",
    "reservations": "ERR_RESERVATION_NOT_FOUND",
    "dues_invoices": "ERR_DUES_INVOICE_NOT_FOUND",
    "transfer_requests": "ERR_TRANSFER_REQUEST_NOT_FOUND",
    "maintenance_windows": "ERR_MAINTENANCE_WINDOW_NOT_FOUND",
    "capital_projects": "ERR_CAPITAL_PROJECT_NOT_FOUND",
    "occupancy_exceptions": "ERR_OCCUPANCY_EXCEPTION_NOT_FOUND",
    "affiliate_agreements": "ERR_AFFILIATE_AGREEMENT_NOT_FOUND",
}


def fetch(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        fail(_SPEC[collection], "%s not found" % collection[:-1].replace("_", " "))
    return row


def maybe(collection, row_id):
    if not isinstance(row_id, str) or not row_id:
        return None
    return fetch(collection, row_id)


def find(collection, row_id):
    """Lookup with no error at all (used before an ownership rung)."""
    return store.get(collection, row_id)
