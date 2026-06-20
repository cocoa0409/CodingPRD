"""Shared service helpers: pagination, validation, serialization, derived fields."""
from datetime import datetime, timedelta

from flask import request

import errors
from db import db

# ---- Domain constants (SCAFFOLD domain_constants / §1.3) ----
RECEIPT_REQUIRED_THRESHOLD_CENTS = 7500
RECEIPT_TOLERANCE_CENTS = 100
STATEMENT_DUE_DAYS = 21
MIN_PAYMENT_FLOOR_CENTS = 2500
MAX_REWARD_PER_TXN_CENTS = 5000
REIMBURSEMENT_CAP_CENTS = 200000
AUTH_BUFFER_DAYS = 2

# ---- Pagination (PRD §2.3) ----
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def parse_pagination():
    """Read limit/offset query params with defaults and clamping."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else PAGE_DEFAULT_LIMIT
    except (ValueError, TypeError):
        limit = PAGE_DEFAULT_LIMIT
    try:
        offset = int(offset) if offset is not None else PAGE_DEFAULT_OFFSET
    except (ValueError, TypeError):
        offset = PAGE_DEFAULT_OFFSET
    if limit < PAGE_MIN_LIMIT:
        limit = PAGE_MIN_LIMIT
    if limit > PAGE_MAX_LIMIT:
        limit = PAGE_MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """Sort by creation order ascending, then slice by pagination params."""
    items = sorted(items, key=lambda r: r.get("_seq", 0))
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return [serialize(r) for r in page], limit, offset, total


# ---- Serialization ----
INTERNAL_FIELDS = {"_seq"}


def serialize(record):
    return {k: v for k, v in record.items() if k not in INTERNAL_FIELDS}


# ---- Lookups (existence -> ERR_NOT_FOUND) ----
def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found: %s" % rid)
    return rec


# ---- Body validation helpers ----
def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err(errors.ERR_VALIDATION, "Missing required field: %s" % f)


def require_positive_int(body, field):
    """Field must be present and a positive integer -> else ERR_INVALID_AMOUNT.

    Presence/type as missing is treated upstream; here we validate the monetary
    positivity rule (PRD §2.10).
    """
    val = body.get(field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_AMOUNT, "%s must be a positive integer." % field)
    if val <= 0:
        raise errors.err(errors.ERR_INVALID_AMOUNT, "%s must be > 0." % field)
    return val


def as_int_field(body, field):
    """Validate an integer monetary input field as present (ERR_VALIDATION) and an int."""
    val = body.get(field)
    if val is None:
        raise errors.err(errors.ERR_VALIDATION, "Missing required field: %s" % field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise errors.err(errors.ERR_VALIDATION, "%s must be an integer." % field)
    return val


def validate_enum(body, field, allowed, required=True):
    val = body.get(field)
    if val is None:
        if required:
            raise errors.err(errors.ERR_VALIDATION, "Missing required field: %s" % field)
        return None
    if val not in allowed:
        raise errors.err(errors.ERR_VALIDATION, "Invalid value for %s: %s" % (field, val))
    return val


# ---- Datetime parsing for clock / windows ----
def to_dt(value):
    """Parse ISO8601 into a comparable naive-UTC datetime. Raise ERR_VALIDATION."""
    if not isinstance(value, str):
        raise errors.err(errors.ERR_VALIDATION, "Invalid datetime value.")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.err(errors.ERR_VALIDATION, "Malformed datetime: %s" % value)
    if dt.tzinfo is not None:
        dt = dt.astimezone().utctimetuple()
        dt = datetime(*dt[:6])
    return dt


def add_days_iso(value, days):
    """Return ISO8601 string for value + days, preserving the Z/3-fractional format."""
    dt = to_dt(value)
    dt = dt + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---- Derived field reconciliation ----
def recompute_held(card):
    """Card.held_cents = sum of amount_cents for this card's tx in {PENDING, CLEARED}."""
    total = 0
    for tx in db.transactions.values():
        if tx["card_id"] == card["id"] and tx["auth_status"] in ("PENDING", "CLEARED"):
            total += tx["amount_cents"]
    card["held_cents"] = total
    return total


def recompute_available_credit(company):
    """available_credit_cents = credit_limit - open_holds - posted_unpaid (PRD §2.6)."""
    cid = company["id"]
    open_holds = 0
    for tx in db.transactions.values():
        if tx["company_id"] == cid and tx["auth_status"] in ("PENDING", "CLEARED"):
            open_holds += tx["amount_cents"]
    posted_unpaid = 0
    for stmt in db.statements.values():
        if stmt["company_id"] == cid and stmt["status"] in ("CLOSED", "DUE", "PAST_DUE"):
            posted_unpaid += stmt["closing_balance_cents"] - stmt["amount_repaid_cents"]
    company["available_credit_cents"] = (
        company["credit_limit_cents"] - open_holds - posted_unpaid
    )
    return company["available_credit_cents"]


def open_statement_for(company_id):
    """Return the company's currently OPEN statement, or None."""
    for stmt in db.statements.values():
        if stmt["company_id"] == company_id and stmt["status"] == "OPEN":
            return stmt
    return None


def reward_account_for(company_id):
    for ra in db.reward_accounts.values():
        if ra["company_id"] == company_id:
            return ra
    return None


# ---- List-filter helpers ----
def q(name):
    """Read a query-string parameter."""
    return request.args.get(name)


def filter_items(items, criteria):
    """Filter records by exact (string-compared) match on the given criteria dict.

    Keys whose value is None are ignored.
    """
    out = items
    for field, value in criteria.items():
        if value is not None:
            out = [r for r in out if str(r.get(field)) == str(value)]
    return out
