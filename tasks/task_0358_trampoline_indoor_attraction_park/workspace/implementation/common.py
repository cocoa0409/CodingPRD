"""Common system-managed fields and serialization (PRD §2.4)."""
from decimal import Decimal, ROUND_HALF_UP

from db import new_id, now_dt, iso_ms


def make_common(with_version=True):
    """Mint id + created_at/updated_at/version.

    A PassAddOn is immutable and leaner (PRD §2.4): it carries only id and
    created_at — no updated_at, no version. Pass with_version=False for it.
    """
    ts = now_dt()
    rec = {
        "id": new_id(),
        "_created_dt": ts,
        "created_at": iso_ms(ts),
    }
    if with_version:
        rec["_updated_dt"] = ts
        rec["updated_at"] = iso_ms(ts)
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation: refresh updated_at and increment version (PRD §2.4)."""
    ts = now_dt()
    rec["_updated_dt"] = ts
    rec["updated_at"] = iso_ms(ts)
    if "version" in rec:
        rec["version"] = rec["version"] + 1


def round_half_up(value):
    """Round a numeric value to the nearest whole cent, half up (PRD §2.8)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# Internal keys (prefixed with _) are never serialized to clients.
def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
