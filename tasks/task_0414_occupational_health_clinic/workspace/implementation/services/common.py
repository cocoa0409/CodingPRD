"""Shared helpers: entity touch (version/timestamp bump), date parsing,
serialization, body-shape validation primitives, employer balance recompute.
"""

from datetime import date, datetime

import errors
from db import db, new_id, next_seq, now_iso
from errors import err


# --- Audit lifecycle ---------------------------------------------------------

def base_entity(versioned=True):
    """Create the standard audit scaffold for a new entity.

    versioned=True -> id, created_at, updated_at, version (all entities except
    CustodyEvent, which is append-only with only id + created_at).
    The internal _seq_create breaks created_at ties for deterministic ordering.
    """
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "_seq_create": next_seq(),
    }
    if versioned:
        ent["updated_at"] = ts
        ent["version"] = 1
    return ent


def touch(entity):
    """Mutation of a versioned entity: refresh updated_at, bump version."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# --- Date helpers ------------------------------------------------------------

def parse_date(value):
    """Parse a UTC date/datetime string into a date. Returns None if unparseable."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Accept bare date or full ISO datetime.
    try:
        if "T" in s:
            s2 = s.replace("Z", "+00:00")
            return datetime.fromisoformat(s2).date()
        return date.fromisoformat(s)
    except ValueError:
        # Fallback: take the leading 10 chars as YYYY-MM-DD
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


def date_of(iso_ts):
    """Date portion of a stored ISO timestamp string."""
    if not iso_ts:
        return None
    try:
        return date.fromisoformat(iso_ts[:10])
    except ValueError:
        return None


# --- Body-shape validation primitives (ERR_INVALID_REQUEST, 400) ------------

def require_body(body):
    if body is None or not isinstance(body, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return body[name]


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or not val.strip():
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if not isinstance(val, str) or val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def optional_enum(body, name, allowed):
    if name not in body or body[name] is None:
        return None
    val = body[name]
    if not isinstance(val, str) or val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def require_bool(body, name):
    val = require_field(body, name)
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return val


def require_int(body, name, non_negative=False):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if non_negative and val < 0:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be >= 0" % name)
    return val


def optional_int(body, name, default=0, non_negative=False):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if non_negative and val < 0:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be >= 0" % name)
    return val


def require_date_field(body, name):
    raw = require_field(body, name)
    d = parse_date(raw)
    if d is None:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a valid date" % name)
    return raw, d


# --- Employer balance recompute (§3.13 / calculations.employer_outstanding_balance) ---

def compute_outstanding_balance(employer):
    """Pure computation: sum (total_cents - paid_cents) over the employer's
    ISSUED/OVERDUE/PARTIALLY_PAID invoices. DRAFT/VOIDED/PAID contribute 0."""
    total = 0
    for inv in db.invoices.values():
        if inv["employer_id"] != employer["id"]:
            continue
        if inv["status"] in ("ISSUED", "OVERDUE", "PARTIALLY_PAID"):
            total += inv["total_cents"] - inv["paid_cents"]
    return total


def recompute_employer_balance(employer):
    """Recompute the balance field. Only bump the employer version/updated_at when
    the derived value actually changes (PRD §2.4: recomputation that mutates a
    derived value is a mutation). The two declared version-bumping write paths
    (protocol activate, invoice issue) change the balance and so bump here; a
    no-op recompute (e.g. voiding a DRAFT that contributed 0) does not bump,
    keeping the employer version aligned with §2.8's explicit list."""
    total = compute_outstanding_balance(employer)
    if employer.get("outstanding_balance_cents") != total:
        employer["outstanding_balance_cents"] = total
        touch(employer)
        return True
    return False
