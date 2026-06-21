"""Shared helpers: record lifecycle, serialization, validation, clock, ledger."""
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, new_id, now_iso
from errors import err
import constants as C


# ---------------------------------------------------------------------------
# Record lifecycle (common system fields, PRD §2.4)
# ---------------------------------------------------------------------------
def base_record(common_fields=True):
    """Create a record dict pre-populated with system-managed fields."""
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
    }
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a full first-class resource."""
    if "version" in rec:
        rec["updated_at"] = now_iso()
        rec["version"] += 1


# ---------------------------------------------------------------------------
# Serialization — strip internal keys (those prefixed with '_')
# ---------------------------------------------------------------------------
def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Round-half-up to whole cents (PRD §2.5)
# ---------------------------------------------------------------------------
def round_half_up_cents(value):
    """value is a Decimal; round half up to an integer number of cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps(base_cents, rate_bps):
    """base * rate_bps / 10000, rounded half up to whole cents."""
    return round_half_up_cents(Decimal(base_cents) * Decimal(rate_bps) / Decimal(10000))


# ---------------------------------------------------------------------------
# Input validation primitives (PRD §2.8)
# ---------------------------------------------------------------------------
def require_int(body, field, minimum=None):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_VALIDATION", f"Field {field} must be >= {minimum}")
    return val


def optional_int(body, field, default=0, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_VALIDATION", f"Field {field} must be >= {minimum}")
    return val


def require_str(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"Field {field} must be a string")
    return val


def optional_str(body, field, default=""):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"Field {field} must be a string")
    return val


def validate_enum(field, value):
    """Raise ERR_INVALID_ENUM if value not in the permitted set for field."""
    allowed = C.ENUMS.get(field)
    if allowed is not None and value not in allowed:
        raise err("ERR_INVALID_ENUM", f"Invalid value for {field}: {value}")
    return value


def require_enum(body, field, default=None):
    if field not in body or body[field] is None:
        if default is not None:
            return default
        raise err("ERR_VALIDATION", f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"Field {field} must be a string")
    return validate_enum(field, val)


def is_four_digits(s):
    return isinstance(s, str) and len(s) == 4 and s.isascii() and s.isdigit()


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination(args):
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, limit, offset):
    """records: already-filtered list. Sort by created_at asc (via _seq) then page."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], total


# ---------------------------------------------------------------------------
# Logical clock (PRD §3.12)
# ---------------------------------------------------------------------------
def parse_iso8601(s):
    if not isinstance(s, str):
        raise err("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 string")
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err("ERR_VALIDATION", "to_iso8601 must be a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    return store.clock


def clock_date():
    return store.clock.date()


def parse_date(s, field="date"):
    """Parse a YYYY-MM-DD calendar date string."""
    if not isinstance(s, str):
        raise err("ERR_VALIDATION", f"{field} must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise err("ERR_VALIDATION", f"{field} must be a YYYY-MM-DD date")


def add_days_to_date(d, days):
    return d + timedelta(days=days)


# ---------------------------------------------------------------------------
# Ledger posting + balance recompute (PRD §2.5, §3)
# ---------------------------------------------------------------------------
def post_ledger(merchant_id, account, amount_cents, entry_type, source_type, source_id):
    """Append an immutable ledger entry (id + created_at only)."""
    entry = base_record(common_fields=False)
    entry["merchant_id"] = merchant_id
    entry["account"] = account
    entry["amount_cents"] = amount_cents
    entry["entry_type"] = entry_type
    entry["source_type"] = source_type
    entry["source_id"] = source_id
    store.ledger_entries[entry["id"]] = entry
    return entry


def recompute_balances(merchant):
    """Recompute available/reserved balances from the ledger; this is itself a
    merchant mutation that bumps version + updated_at (PRD §2.6)."""
    mid = merchant["id"]
    available = 0
    reserved = 0
    for e in store.ledger_entries.values():
        if e["merchant_id"] != mid:
            continue
        if e["account"] == "AVAILABLE":
            available += e["amount_cents"]
        elif e["account"] == "RESERVE":
            reserved += e["amount_cents"]
    merchant["available_balance_cents"] = available
    merchant["reserved_balance_cents"] = reserved
    touch(merchant)
