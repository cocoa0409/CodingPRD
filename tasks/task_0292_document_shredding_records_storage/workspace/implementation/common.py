"""Shared helpers: serialization, pagination, lookups, field validation."""
from decimal import ROUND_HALF_UP, Decimal

from flask import request

from db import db
from errors import err

# Public (API-exposed) field names per entity. The internal helper fields
# (_seq, and certain internal-only keys) are stripped on serialization.
_INTERNAL_KEYS = {"_seq"}


def serialize(entity):
    """Return a copy of the entity with internal-only keys removed."""
    return {k: v for k, v in entity.items() if k not in _INTERNAL_KEYS}


def paginate(items):
    """Apply limit/offset pagination (PRD §2.3).

    limit defaults to 10, min 1, max 100. offset defaults to 0.
    Invalid pagination values -> ERR_INVALID_FIELD_VALUE (422)? The PRD §2.3
    constrains limit to [1,100] and offset >= 0. We clamp-validate per spec.
    Returns (page_items, limit, offset, total_count).
    """
    total = len(items)
    limit = _parse_int_param("limit", 10)
    offset = _parse_int_param("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    page = items[offset:offset + limit]
    return page, limit, offset, total


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def sort_by_created(items):
    """Default list sort: created_at ascending, insertion order as tiebreak."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def body():
    """Return the JSON body as a dict (empty dict if none / not JSON)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


# ---- Field validation helpers (ERR_INVALID_FIELD_VALUE, 422) ----

def require_present(data, *names):
    for n in names:
        if n not in data or data[n] is None:
            raise err("ERR_INVALID_FIELD_VALUE", "Missing required field: %s" % n)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_FIELD_VALUE", "Invalid value for %s" % field)


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_FIELD_VALUE", "%s must be an integer" % field)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_FIELD_VALUE", "%s must be a number" % field)
    return value


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_FIELD_VALUE", "%s must be a non-empty string" % field)
    return value


def round_half_up_cents(decimal_value):
    """Round a Decimal to an integer number of cents, round-half-up (PRD §2.7)."""
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_kg(decimal_value):
    """Round a weight to 3 decimal places, round-half-up (PRD §2.7)."""
    q = decimal_value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---- Existence lookups (PRD §2.6 resource resolution) ----

def get_account_or_404(account_id):
    a = db.accounts.get(account_id)
    if a is None:
        raise err("ERR_ACCOUNT_NOT_FOUND", "Account not found")
    return a


def get_order_or_404(order_id):
    o = db.service_orders.get(order_id)
    if o is None:
        raise err("ERR_ORDER_NOT_FOUND", "Service order not found")
    return o


def get_box_or_404(box_id):
    b = db.retention_boxes.get(box_id)
    if b is None:
        raise err("ERR_BOX_NOT_FOUND", "Retention box not found")
    return b


def get_request_or_404(request_id):
    r = db.retrieval_requests.get(request_id)
    if r is None:
        raise err("ERR_REQUEST_NOT_FOUND", "Retrieval request not found")
    return r


def get_location_or_404(location_id):
    loc = db.locations.get(location_id)
    if loc is None:
        raise err("ERR_NOT_FOUND", "Location not found")
    return loc


def get_container_or_404(container_id):
    c = db.containers.get(container_id)
    if c is None:
        raise err("ERR_NOT_FOUND", "Container not found")
    return c


def get_rate_card_or_404(card_id):
    c = db.rate_cards.get(card_id)
    if c is None:
        raise err("ERR_NOT_FOUND", "Rate card not found")
    return c


def get_certificate_or_404(cert_id):
    c = db.certificates.get(cert_id)
    if c is None:
        raise err("ERR_NOT_FOUND", "Certificate not found")
    return c


def get_destruction_invoice_or_404(inv_id):
    i = db.destruction_invoices.get(inv_id)
    if i is None:
        raise err("ERR_NOT_FOUND", "Destruction invoice not found")
    return i


def get_storage_invoice_or_404(inv_id):
    i = db.storage_invoices.get(inv_id)
    if i is None:
        raise err("ERR_NOT_FOUND", "Storage invoice not found")
    return i


def get_hold_or_404(hold_id):
    h = db.compliance_holds.get(hold_id)
    if h is None:
        raise err("ERR_NOT_FOUND", "Compliance hold not found")
    return h


def get_weight_ticket_or_404(ticket_id):
    t = db.weight_tickets.get(ticket_id)
    if t is None:
        raise err("ERR_NOT_FOUND", "Weight ticket not found")
    return t


def get_custody_event_or_404(event_id):
    e = db.custody_events.get(event_id)
    if e is None:
        raise err("ERR_NOT_FOUND", "Custody event not found")
    return e


# ---- Shared business helpers ----

def active_rate_card(account_id):
    """Return the single ACTIVE rate card for the account, or None."""
    for c in db.rate_cards.values():
        if c["account_id"] == account_id and c["status"] == "ACTIVE":
            return c
    return None


def has_active_hold(subject_type, subject_id):
    for h in db.compliance_holds.values():
        if (h["status"] == "ACTIVE"
                and h["subject_type"] == subject_type
                and h["subject_id"] == subject_id):
            return True
    return False
