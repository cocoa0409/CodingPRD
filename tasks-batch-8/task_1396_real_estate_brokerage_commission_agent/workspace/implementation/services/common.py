"""Shared service helpers: id generation, resource scaffolding, money math."""

import uuid
from decimal import Decimal, ROUND_HALF_UP

from timeutil import logical_stamp


def new_id():
    return str(uuid.uuid4())


def stamp_new(resource):
    """Attach common system fields for a primary resource (PRD §2.5)."""
    ts = logical_stamp()
    resource["created_at"] = ts
    resource["updated_at"] = ts
    resource["version"] = 1
    return resource


def stamp_append_only(resource):
    """Ledger entries and trust transactions carry only id + created_at."""
    resource["created_at"] = logical_stamp()
    return resource


def touch(resource):
    """Refresh updated_at and bump version on a mutation."""
    resource["updated_at"] = logical_stamp()
    resource["version"] = resource.get("version", 1) + 1
    return resource


def cents_half_up(value):
    """Round a Decimal/float/int to whole cents with ROUND_HALF_UP."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_pct(pct, cents):
    """pct * cents rounded half up to whole cents (per-step rounding rule)."""
    d = (Decimal(str(pct)) * Decimal(int(cents))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)
