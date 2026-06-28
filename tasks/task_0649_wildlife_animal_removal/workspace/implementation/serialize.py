"""Public serialization of internal records.

Strips private fields (those beginning with '_') and returns a plain dict that is
safe to emit in the response envelope. Internal records already carry exactly the
public field set plus a handful of private bookkeeping keys, so a generic filter
is sufficient and keeps every declared field (id/created_at/updated_at/version
plus entity-specific fields).
"""


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}
