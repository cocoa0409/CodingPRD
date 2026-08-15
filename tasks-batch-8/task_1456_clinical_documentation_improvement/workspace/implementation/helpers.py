"""Shared helpers: record factory, OCC/touch, lookups, program gate, lists."""
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import timestamp
from errors import raise_error
from middleware import parse_pagination


def make_record(collection, fields):
    rec_id = db.new_id()
    ts = timestamp()
    rec = {
        "id": rec_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    collection[rec_id] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version (PRD 2.4: every modification)."""
    rec["updated_at"] = timestamp()
    rec["version"] += 1


def get_or_404(collection, rec_id, label="resource"):
    rec = collection.get(rec_id)
    if rec is None:
        raise_error("ERR_NOT_FOUND", f"{label} not found: {rec_id}")
    return rec


def body_ref(body, field, collection, label):
    """Resolve a required body-carried FK reference (400 when unresolvable)."""
    val = body.get(field)
    if not isinstance(val, str) or not val:
        raise_error("ERR_INVALID_REQUEST", f"{field} is required and must be a string")
    rec = collection.get(val)
    if rec is None:
        raise_error(
            "ERR_INVALID_REQUEST",
            f"{field} does not reference an existing {label}",
        )
    return rec


def program_of(entity):
    return db.programs.get(entity["cdi_program_id"])


def require_program_active(program):
    """PRD 2.6: programs not in ACTIVE refuse nearly all writes."""
    if program is not None and program["status"] != "ACTIVE":
        raise_error(
            "ERR_PROGRAM_NOT_ACTIVE",
            f"Program {program['id']} is {program['status']}; writes are gated",
        )


def dec4(value):
    """Coerce a JSON number to a 4-decimal Decimal, half-up."""
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def num4(value):
    return float(dec4(value))


def validate_weight(value, field):
    """DRG weight / CMI input: numeric, >= 0.1000, stored at 4dp half-up."""
    from middleware import validate_number

    validate_number(value, field)
    if Decimal(str(value)) < Decimal("0.1"):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be at least 0.1000")
    return num4(value)


def list_page(items):
    """Sort by creation order and apply limit/offset pagination."""
    items = sorted(items, key=lambda r: r["_seq"])
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
