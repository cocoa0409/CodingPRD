"""Shared record helpers: common system fields and mutation bookkeeping."""

from db import new_id, now_iso


def base_record(common_fields=True):
    """Create the id + system fields shared by (almost) all entities.

    TaxStatement is the lone exception (common_fields=False): it carries only
    id and created_at — no updated_at, no version (PRD §2.4).
    """
    rec = {"id": new_id(), "created_at": now_iso()}
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on any mutation (PRD §2.4, §2.9)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
